"""Bet placement executor making paper or live trades on Polymarket."""

import json
import logging
import os
from datetime import UTC, datetime

from sqlalchemy import func

from config.settings import Config, bot_config
from database.db import get_session
from database.models import OPEN_BET_STATUSES, Analysis, Bet, Portfolio, WeatherMarket
from utils.price_sanity import is_valid_binary_price

logger = logging.getLogger("EXECUTOR_BET_PLACER")


class BetPlacer:
    """SADECE bet açar. Karar vermez - engine karar verir."""

    # Statuses that count as "open" for risk/exposure accounting.
    _OPEN_STATUSES = OPEN_BET_STATUSES

    def __init__(self):
        # Lazy-import risk manager to break import cycle:
        #   engine/strategy.py  ->  imports from this module
        #   executor/bet_placer.py  ->  uses engine.strategy.RiskManager
        from engine.strategy import RiskManager

        self.risk_manager = RiskManager()

        # Hard guard: the user requires paper-only mode.
        if Config.DRY_RUN:
            self.ready = False
            logger.info(
                "DRY_RUN=true is enforced. BetPlacer will ONLY emit paper/simulated "
                "orders; the live Polymarket CLOB client is not initialized."
            )
        else:
            self._init_polymarket_client()

    def _init_polymarket_client(self):
        """Polymarket CLOB client hazirla (sadece DRY_RUN=false ise cagrilir)."""
        try:
            from py_clob_client.client import ClobClient  # pylint: disable=import-error,no-name-in-module

            if not bot_config.polymarket.private_key:
                self.ready = False
                logger.info("Polymarket credentials not found, running in PAPER/SIMULATION trade mode.")
                return

            self.client = ClobClient(
                bot_config.polymarket.api_url,
                key=bot_config.polymarket.private_key,
                chain_id=137,
            )
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
            self.ready = True
            logger.warning(
                "LIVE TRADING ARMED -- DRY_RUN=false and credentials present. Real orders will be sent to Polymarket."
            )
        except Exception as e:
            logger.warning(f"Polymarket client kurulamadi (PAPER TRADE ACTIVE): {e}")
            self.ready = False

    def place_bet(self, analysis_id: int) -> Bet | None:
        """Analiz sonucuna göre bet aç."""
        with get_session() as session:
            analysis = session.query(Analysis).filter_by(id=analysis_id).first()
            if not analysis or not analysis.should_bet:
                return None

            market = session.query(WeatherMarket).filter_by(id=analysis.market_id).first()
            if not market:
                return None

            # Price sanity check - skip invalid binary markets
            if not is_valid_binary_price(market.yes_price or 0, market.no_price or 0):
                logger.debug(
                    f"Market {market.id}: invalid prices yes={market.yes_price}, no={market.no_price}, skipping bet"
                )
                return None

            # Guard: skip resolved markets
            _now = datetime.now(UTC).replace(tzinfo=None)
            if market.target_date and market.target_date <= _now:
                logger.debug(f"Market {market.id}: target_date passed, skipping")
                return None

            # Guard: skip markets with no real liquidity
            market_price = float(market.yes_price or 0.5)
            min_price = float(getattr(self.risk_manager.config, "MIN_ENTRY_PRICE", 0.01))
            if market_price < min_price:
                logger.debug(f"Market {market.id}: target_date passed, skipping")
                return None

            # Zaten bet açılmış mı?
            existing = (
                session.query(Bet)
                .filter(Bet.market_id == analysis.market_id, Bet.status.in_(self._OPEN_STATUSES))
                .first()
            )
            if existing:
                logger.info(f"Market {market.id} already has a bet")
                return None

            # ------------------------------------------------------------------
            # Sync RiskManager portfolio_value with CONSERVATIVE value
            # (initial + realized_pnl) NOT Portfolio.total_value which can be
            # inflated by stale paper bets.
            _initial = float(self.risk_manager.config.INITIAL_PORTFOLIO)
            _realized = float(
                session.query(func.coalesce(func.sum(Bet.pnl), 0.0))
                .filter(Bet.status.in_(("won", "lost", "settled")))
                .scalar()
                or 0.0
            )
            self.risk_manager.update_portfolio(_initial + _realized)

            # Risk checks. These are enforced HERE (not in run_place_bets)
            # so every entry point "" scheduler, manual API call, CLI "" is
            # guarded by the same hard caps. A previous version of this
            # module skipped all caps and let exposure balloon to 35x the
            # smart-pool ceiling, which is what surfaced the
            # "$14,000 exposure vs $400 smart pool" dashboard disconnect.
            # ------------------------------------------------------------------
            proposed_amount = float(analysis.recommended_amount or 0.0)

            # Optional flat-bet override: when Config.FLAT_BET_USD > 0,
            # every bet is exactly that many USD, ignoring Kelly sizing.
            # Useful for backtests and small-portfolio testing where
            # Kelly-derived sizes would otherwise be too small to matter.
            # Risk caps below still apply on top.
            flat_bet = float(getattr(self.risk_manager.config, "FLAT_BET_USD", 0.0) or 0.0)
            if flat_bet > 0.0:
                logger.info(
                    f"Flat-bet override active: ${flat_bet:.2f} per bet (was ${proposed_amount:.2f} from Kelly)."
                )
                proposed_amount = flat_bet

            # Cap 1: per-bet cap (MAX_BET_PCT * portfolio). The engine's
            # Kelly sizing already enforces this in calculator.py, but
            # we re-apply it here as a hard ceiling.
            max_bet = float(self.risk_manager.portfolio_value) * float(self.risk_manager.config.MAX_BET_PCT)
            if proposed_amount > max_bet:
                logger.warning(
                    f"Risk cap: Market {market.id} amount ${proposed_amount:.2f} "
                    f"exceeds per-bet max ${max_bet:.2f} — clamping."
                )
                proposed_amount = max_bet

            # Cap 2: total exposure cap (TOTAL_EXPOSURE_PCT * conservative portfolio).
            # check_exposure_cap now dynamically computes conservative value
            # (cash + open_exposure) from DB, so no stale portfolio_value.
            current_exposure = (
                session.query(func.coalesce(func.sum(Bet.amount), 0.0))
                .filter(Bet.status.in_(self._OPEN_STATUSES))
                .scalar()
            ) or 0.0
            current_exposure = float(current_exposure)
            if not self.risk_manager.check_exposure_cap(current_exposure, proposed_amount):
                max_exposure = float(self.risk_manager.portfolio_value) * float(
                    self.risk_manager.config.TOTAL_EXPOSURE_PCT
                )
                logger.warning(
                    f"Risk cap: Market {market.id} rejected — exposure would "
                    f"reach ${current_exposure + proposed_amount:.2f}, "
                    f"exceeding cap ${max_exposure:.2f}."
                )
                # Record a synthetic "rejected" bet row for audit visibility
                # so the user can see WHY exposure is being held back.
                rejected = Bet(
                    market_id=analysis.market_id,
                    analysis_id=analysis_id,
                    city=market.city,
                    city_code=market.city_code,
                    side=analysis.recommended_side,
                    amount=proposed_amount,
                    price=market.yes_price if analysis.recommended_side == "YES" else market.no_price,
                    status="rejected",
                    error_message=(
                        f"Exposure cap: ${current_exposure:.2f} + ${proposed_amount:.2f} > ${max_exposure:.2f}"
                    ),
                )
                session.add(rejected)
                session.commit()
                return None

            # Cap 3: city cap (CITY_CAP per city).
            city_key = (market.city or "").lower()
            city_open_count = (
                session.query(func.count(Bet.id))  # pylint: disable=not-callable
                .join(WeatherMarket, Bet.market_id == WeatherMarket.id)
                .filter(
                    Bet.status.in_(self._OPEN_STATUSES),
                    func.lower(WeatherMarket.city) == city_key,
                )
                .scalar()
            ) or 0
            if int(city_open_count) >= int(self.risk_manager.config.CITY_CAP):
                logger.warning(
                    f"Risk cap: Market {market.id} rejected — city cap "
                    f"({city_open_count}/{self.risk_manager.config.CITY_CAP}) "
                    f"reached for {market.city}."
                )
                rejected = Bet(
                    market_id=analysis.market_id,
                    analysis_id=analysis_id,
                    city=market.city,
                    city_code=market.city_code,
                    side=analysis.recommended_side,
                    amount=proposed_amount,
                    price=market.yes_price if analysis.recommended_side == "YES" else market.no_price,
                    status="rejected",
                    error_message=f"City cap: {city_open_count}/{self.risk_manager.config.CITY_CAP} for {market.city}",
                )
                session.add(rejected)
                session.commit()
                return None

            # Resolve fill price for the chosen side
            fill_price = market.yes_price if analysis.recommended_side == "YES" else market.no_price
            fill_price = float(fill_price) if fill_price is not None else 0.0
            # Shares = amount / price (position size in contracts)
            shares = (proposed_amount / fill_price) if fill_price > 0 else 0.0

            # Bet objesi oluştur
            fair_value = float(analysis.estimated_probability or 0.5)
            bet = Bet(
                market_id=analysis.market_id,
                analysis_id=analysis_id,
                city=market.city,  # FIX: copy city from market so the
                city_code=market.city_code,  # dashboard "City" column is populated
                side=analysis.recommended_side,
                amount=proposed_amount,
                price=fill_price,
                entry_price=fill_price,  # NEW: source of truth for PNL math
                shares=shares,  # NEW: needed for unrealized_pnl
                current_price=fill_price,  # NEW: starts equal to entry, refreshed by run_update_prices
                status="pending",
                fair_value=fair_value,
                expected_value=float(analysis.edge or 0.0),
            )

            bet.potential_payout = bet.amount / bet.price if bet.price > 0 else 0

            # Paper ladder: if edge >= 0.05, create a 3-level ladder
            ladder_orders = []
            edge_val = float(analysis.edge or 0.0)
            if abs(edge_val) >= 0.05:
                for lvl, pct in [(1, 0.50), (2, 0.30), (3, 0.20)]:
                    lvl_amount = round(proposed_amount * pct, 2)
                    if lvl == 1:
                        lvl_price = fill_price
                    elif lvl == 2:
                        lvl_price = fill_price * 0.98
                    else:
                        lvl_price = fill_price * 0.95
                    # Clamp price to [0.01, 0.99]
                    lvl_price = max(0.01, min(0.99, round(lvl_price, 4)))
                    lvl_shares = round(lvl_amount / lvl_price, 4) if lvl_price > 0 else 0.0
                    ladder_orders.append(
                        {
                            "level": lvl,
                            "price": lvl_price,
                            "amount": lvl_amount,
                            "shares": lvl_shares,
                            "status": "pending",
                        }
                    )
            bet.ladder_data = json.dumps(ladder_orders) if ladder_orders else "[]"

            # Live vs Paper execution logic
            # HARD GUARD: always paper unless LIVE_TRADING_ENABLED=true
            _live_allowed = (not Config.DRY_RUN) and os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
            if self.ready and _live_allowed:
                try:
                    from py_clob_client.order_builder.constants import (
                        BUY,  # pylint: disable=import-error,no-name-in-module
                    )

                    order = self.client.create_and_post_order(
                        {
                            "token_id": self._get_token_id(market, analysis.recommended_side),
                            "price": bet.price,
                            "size": bet.amount / bet.price,
                            "side": BUY,
                        }
                    )

                    bet.order_id = order.get("orderID")
                    bet.status = "placed"
                    bet.placed_at = datetime.now(UTC).replace(tzinfo=None)

                    market.status = "bet_placed"
                    logger.info(
                        f"LIVE BET OPENED: {market.id} | {analysis.recommended_side} ${bet.amount:.2f} @ {bet.price}"
                    )
                except Exception as e:
                    bet.status = "failed"
                    bet.error_message = str(e)
                    logger.error(f"Live Bet failed {market.id}: {e}")
            else:
                # Simulated / Paper trade fallback. Also covers the case
                # where Config.DRY_RUN is true (defense-in-depth).
                now_ts = int(datetime.now(UTC).replace(tzinfo=None).timestamp())
                bet.order_id = f"paper_order_{market.id}_{now_ts}"
                bet.status = "placed"
                bet.placed_at = datetime.now(UTC).replace(tzinfo=None)
                market.status = "bet_placed"
                logger.info(
                    f"PAPER BET OPENED: {market.id} | "
                    f"{analysis.recommended_side} ${bet.amount:.2f} @ {bet.price} "
                    f"({shares:.2f} shares)"
                )

            # Deduct stake from portfolio cash — via central accounting API.
            # Ladder: L1 is filled immediately; L2/L3 stay pending.
            from utils.accounting import debit_stake

            initial_stake = proposed_amount
            if ladder_orders:
                l1_amount = ladder_orders[0].get("amount") if isinstance(ladder_orders[0], dict) else None
                if l1_amount and l1_amount > 0:
                    initial_stake = l1_amount
                    # Mark L1 as filled immediately (prevents double-debit in run_update_prices)
                    ladder_orders[0]["status"] = "filled"
                    ladder_orders[0]["filled_at"] = datetime.now(UTC).isoformat()
                    # Persist updated ladder back to bet.ladder_data
                    bet.ladder_data = json.dumps(ladder_orders)
            try:
                debit_stake(session, initial_stake, f"bet_open:{bet.market_id}")
            except ValueError as e:
                logger.error("Cannot open bet %s: %s", bet.market_id, e)
                bet.status = "failed"
                bet.error_message = str(e)
                session.add(bet)
                session.commit()
                return bet
            portfolio = session.query(Portfolio).filter(Portfolio.id == 1).first()
            if portfolio:
                portfolio.current_value = portfolio.cash_balance  # unrealized PnL added later (Faz 4)
                portfolio.last_updated = datetime.now(UTC).replace(tzinfo=None)
            session.add(bet)
            session.commit()
            return bet

    def _get_token_id(self, market, side: str) -> str:
        """Market'ten token ID al."""
        raw = json.loads(market.raw_data) if market.raw_data else {}
        tokens = raw.get("tokens", [])
        for token in tokens:
            if token.get("outcome", "").upper() == side.upper():
                return token.get("token_id")
        raise ValueError(f"Token ID bulunamadı: {side}")

    def place_all_pending(self) -> int:
        """should_bet=True olan tüm analizler için bet aç."""
        placed = 0
        with get_session() as session:
            pending = session.query(Analysis).filter(Analysis.should_bet.is_(True)).all()
            analysis_ids = [a.id for a in pending]

            # Dedup: skip analysis_ids that already have ANY Bet record
            processed = set()
            if analysis_ids:
                existing_rows = session.query(Bet.analysis_id).filter(Bet.analysis_id.in_(analysis_ids)).all()
                processed = {row[0] for row in existing_rows if row[0] is not None}

        for aid in analysis_ids:
            if aid in processed:
                logger.debug("Analysis %d already has a bet, skipping", aid)
                continue
            try:
                bet = self.place_bet(aid)
                if bet is not None:
                    placed += 1
            except Exception as e:
                logger.error(f"Bet hatası (analysis {aid}): {e}")
                continue

        return placed
