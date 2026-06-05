"""Bet placement executor making paper or live trades on Polymarket."""

import json
import logging
from datetime import datetime, timezone
from database.db import get_session
from database.models import Analysis, Bet, WeatherMarket
from config.settings import bot_config

logger = logging.getLogger("EXECUTOR_BET_PLACER")


class BetPlacer:
    """SADECE bet açar. Karar vermez - engine karar verir."""

    def __init__(self):
        self._init_polymarket_client()

    def _init_polymarket_client(self):
        """Polymarket CLOB client'ı hazırla."""
        try:
            from py_clob_client.client import ClobClient
            if not bot_config.polymarket.private_key:
                self.ready = False
                logger.info("Polymarket credentials not found, running in PAPER/SIMULATION trade mode.")
                return

            self.client = ClobClient(
                bot_config.polymarket.api_url,
                key=bot_config.polymarket.private_key,
                chain_id=137,  # Polygon
            )
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
            self.ready = True
            logger.info("Polymarket CLOB Client ready for LIVE execution!")
        except Exception as e:
            logger.warning(f"Polymarket client kurulamadı (PAPER TRADE ACTIVE): {e}")
            self.ready = False

    def place_bet(self, analysis_id: int) -> Bet | None:
        """Analiz sonucuna göre bet aç."""
        with get_session() as session:
            analysis = session.query(Analysis).filter_by(id=analysis_id).first()
            if not analysis or not analysis.should_bet:
                return None

            market = session.query(WeatherMarket).filter_by(
                id=analysis.market_id
            ).first()
            if not market:
                return None

            # Zaten bet açılmış mı?
            existing = session.query(Bet).filter(
                Bet.market_id == analysis.market_id,
                Bet.status.in_(["pending", "placed"])
            ).first()
            if existing:
                logger.info(f"Market {market.id} için zaten bet var")
                return None

            # Bet objesi oluştur
            bet = Bet(
                market_id=analysis.market_id,
                analysis_id=analysis_id,
                side=analysis.recommended_side,
                amount=analysis.recommended_amount,
                price=market.yes_price if analysis.recommended_side == "YES" else market.no_price,
                status="pending",
            )

            bet.potential_payout = bet.amount / bet.price if bet.price > 0 else 0

            # Live vs Paper execution logic
            if self.ready:
                try:
                    from py_clob_client.order_builder.constants import BUY

                    order = self.client.create_and_post_order({
                        "token_id": self._get_token_id(market, analysis.recommended_side),
                        "price": bet.price,
                        "size": bet.amount / bet.price,
                        "side": BUY,
                    })

                    bet.order_id = order.get("orderID")
                    bet.status = "placed"
                    bet.placed_at = datetime.now(timezone.utc)

                    market.status = "bet_placed"
                    logger.info(
                        f"🎯 LIVE BET AÇILDI: {market.id} | "
                        f"{analysis.recommended_side} ${bet.amount:.2f} @ {bet.price}"
                    )
                except Exception as e:
                    bet.status = "failed"
                    bet.error_message = str(e)
                    logger.error(f"❌ Live Bet açılamadı {market.id}: {e}")
            else:
                # Simulated / Paper trade fallback
                bet.order_id = f"paper_order_{market.id}_{int(datetime.utcnow().timestamp())}"
                bet.status = "placed"
                bet.placed_at = datetime.utcnow()
                market.status = "bet_placed"
                logger.info(
                    f"📝 PAPER BET AÇILDI: {market.id} | "
                    f"{analysis.recommended_side} ${bet.amount:.2f} @ {bet.price}"
                )

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
            pending = session.query(Analysis).filter(
                Analysis.should_bet
            ).all()
            analysis_ids = [a.id for a in pending]

        for aid in analysis_ids:
            try:
                bet = self.place_bet(aid)
                if bet and bet.status == "placed":
                    placed += 1
            except Exception as e:
                logger.error(f"Bet hatası (analysis {aid}): {e}")
                continue

        return placed
