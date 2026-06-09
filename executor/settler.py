"""Settlement engine: resolves bets when markets close, calculates PnL."""

import json
import logging
from datetime import datetime, timezone
from database.db import get_session
from database.models import Bet, WeatherMarket, Portfolio
from config.settings import config
import requests  # pylint: disable=import-error

logger = logging.getLogger("EXECUTOR_SETTLER")


class SettlementEngine:
    """Resolves open bets by comparing Polymarket outcome with bet side."""

    def __init__(self):
        self.fee_rate = float(getattr(config, "FEE_DRAG", 0.02))

    def settle_all(self) -> dict:
        """Settle all markets whose target_date has passed.

        Returns dict with keys: win, loss, pending, total_pnl.
        """
        won_count = 0
        lost_count = 0
        pending_count = 0
        total_pnl = 0.0

        with get_session() as session:
            now = datetime.now(timezone.utc).replace(tzinfo=None)

            # Find markets that should be settled
            open_statuses = ("open", "bet_placed")
            markets_to_settle = (
                session.query(WeatherMarket)
                .filter(
                    WeatherMarket.status.in_(open_statuses),
                    WeatherMarket.target_date <= now,
                )
                .all()
            )

            if not markets_to_settle:
                logger.info("Settlement: No markets to settle")
                return {"win": 0, "loss": 0, "pending": 0, "total_pnl": 0.0}

            for market in markets_to_settle:
                try:
                    result = self._settle_market(session, market)
                    if result is None:
                        pending_count += 1
                    elif result["won"]:
                        won_count += 1
                        total_pnl += result["pnl"]
                    else:
                        lost_count += 1
                        total_pnl += result["pnl"]
                except Exception as e:
                    logger.error(
                        "Settlement error for market %s: %s", market.id, e,
                        exc_info=True,
                    )
                    pending_count += 1

            session.commit()

        # Post-settlement portfolio sync: all bets are settled, so
        # exposure=0, unrealized=0, total_value=cash_balance.
        if markets_to_settle:
            with get_session() as sync_session:
                portfolio = sync_session.query(Portfolio).filter(Portfolio.id == 1).first()
                if portfolio:
                    portfolio.total_value = portfolio.cash_balance
                    portfolio.current_value = portfolio.cash_balance
                    portfolio.last_updated = datetime.now(timezone.utc).replace(tzinfo=None)
                    sync_session.commit()

        logger.info(
            "Settlement complete: %s won, %s lost, %s pending, total_pnl=%.2f",
            won_count, lost_count, pending_count, total_pnl,
        )
        return {
            "win": won_count,
            "loss": lost_count,
            "pending": pending_count,
            "total_pnl": total_pnl,
        }

    def _settle_market(self, session, market) -> dict | None:
        """Settle a single market. Returns {won, pnl} or None."""
        open_bets = (
            session.query(Bet)
            .filter(
                Bet.market_id == market.id,
                Bet.status.in_(("active", "open", "placed", "pending")),
            )
            .all()
        )

        if not open_bets:
            market.status = "expired"
            return None

        # Get actual weather data
        actual_temp = self._get_actual_temperature(market)
        if actual_temp is None:
            logger.warning(
                "Cannot get actual temp for %s, skipping", market.id
            )
            return None

        strike = float(market.threshold or 0)

        # Determine outcome: YES wins if temp exceeds strike (HIGH/MAX market)
        if "LOW" in str(market.market_type or "").upper():
            outcome_yes = actual_temp < strike
        else:
            # Default HIGH: YES wins if actual > strike
            outcome_yes = actual_temp > strike

        outcome = "YES" if outcome_yes else "NO"

        logger.info(
            "Market %s: actual=%.1f, strike=%.1f, outcome=%s",
            market.id, actual_temp, strike, outcome,
        )

        total_market_pnl = 0.0
        any_settled = False
        any_bet_won = False

        for bet in open_bets:
            bet_won = (bet.side == outcome)
            if bet_won:
                any_bet_won = True
            bet.status = "won" if bet_won else "lost"
            bet.settled_at = datetime.now(timezone.utc).replace(tzinfo=None)

            stake = float(bet.amount or 0)
            entry_price = float(bet.entry_price or bet.price or 0.5)

            if bet_won:
                payout = stake / entry_price if entry_price > 0 else 0.0
                fee = payout * self.fee_rate
                realized_pnl = payout - stake - fee
            else:
                fee = stake * self.fee_rate
                realized_pnl = -stake - fee

            bet.realized_pnl = round(realized_pnl, 2)
            bet.pnl = round(realized_pnl, 2)
            bet.unrealized_pnl = 0.0  # Settled = no unrealized left
            total_market_pnl += realized_pnl
            any_settled = True

            # Update portfolio
            portfolio = session.query(Portfolio).filter(
                Portfolio.id == 1
            ).first()
            if portfolio:
                if bet_won:
                    portfolio.cash_balance = (
                        (portfolio.cash_balance or 0) + payout - fee
                    )
                    portfolio.total_won = (portfolio.total_won or 0) + 1
                else:
                    portfolio.total_lost = (portfolio.total_lost or 0) + 1
                portfolio.total_realized_pnl = (
                    (portfolio.total_realized_pnl or 0) + realized_pnl
                )

        if any_settled:
            market.status = "settled_win" if outcome_yes else "settled_loss"
            market.resolution_data = json.dumps({
                "actual_temperature": actual_temp,
                "strike": strike,
                "outcome": outcome,
                "settled_at": datetime.now(timezone.utc).isoformat(),
            })

        return {"won": any_bet_won, "pnl": total_market_pnl}

    def _get_actual_temperature(self, market) -> float | None:
        """Fetch actual temperature from Open-Meteo historical API."""
        try:
            lat = market.latitude or 0
            lon = market.longitude or 0
            target_date = market.target_date

            if not lat or not lon or not target_date:
                return None

            date_str = target_date.strftime("%Y-%m-%d")

            url = "https://archive-api.open-meteo.com/v1/archive"
            params = {
                "latitude": lat,
                "longitude": lon,
                "start_date": date_str,
                "end_date": date_str,
                "daily": "temperature_2m_max,temperature_2m_min",
                "temperature_unit": "celsius",
                "timezone": "auto",
            }

            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            daily = data.get("daily", {})
            max_vals = daily.get("temperature_2m_max")
            min_vals = daily.get("temperature_2m_min")

            if max_vals and max_vals[0] is not None:
                return float(max_vals[0])
            if min_vals and min_vals[0] is not None:
                return float(min_vals[0])

            return None

        except Exception as e:
            logger.warning(
                "Historical weather fetch failed for %s: %s", market.id, e
            )
            return None
