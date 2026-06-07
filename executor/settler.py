"""Settlement checking and executing paper/live payout calculations."""

import logging
import requests
from datetime import datetime, timezone
from database.db import get_session
from database.models import Bet, WeatherMarket, Portfolio, Market

logger = logging.getLogger("EXECUTOR_SETTLER")


class Settler:
    """Checks and resolves old bets against historical actual weather data."""

    def check_settlement(self, bet_id: int) -> str | None:
        """Bir betin sonucunu kontrol et."""
        with get_session() as session:
            bet = session.query(Bet).filter_by(id=bet_id).first()
            if not bet or bet.status not in ("placed", "pending", "active"):
                return None

            market = session.query(WeatherMarket).filter_by(
                id=bet.market_id
            ).first()
            if not market:
                # Compatibility check
                m = session.query(Market).filter_by(market_id=bet.market_id).first()
                if m:
                    market = WeatherMarket(
                        id=m.market_id,
                        city=m.city,
                        threshold=m.strike_temp,
                        target_date=m.resolution_date,
                        metric=m.outcome_type,
                    )
            if not market:
                return None

            # Tarih henüz gelmedi mi?
            if market.target_date and market.target_date > datetime.now(timezone.utc).replace(tzinfo=None):
                return None

            # Gerçek hava verisini çek (geçmiş veri)
            actual = self._get_actual_weather(market)

            if actual is None:
                logger.warning(f"Gerçek veri bulunamadı: {market.id}")
                return None

            bet.actual_value = actual

            # Sonuç belirleme
            threshold_exceeded = actual > market.threshold

            if (bet.side == "YES" and threshold_exceeded) or \
               (bet.side == "NO" and not threshold_exceeded):
                bet.status = "won"
                bet.pnl = bet.potential_payout - bet.amount
                market.status = "settled_win"
                result = "WIN"
            else:
                bet.status = "lost"
                bet.pnl = -bet.amount
                market.status = "settled_loss"
                result = "LOSS"

            bet.settled_at = datetime.now(timezone.utc).replace(tzinfo=None)

            # Update portfolio with correct cash accounting:
            # - WIN:  credit full payout (stake was already deducted at placement)
            # - LOSS: nothing to credit (stake was already deducted at placement)
            # PnL is tracked for analytics but cash flow determines the balance.
            portfolio = session.query(Portfolio).filter(Portfolio.id == 1).first()
            if portfolio:
                portfolio.total_realized_pnl += bet.pnl
                if result == "WIN":
                    # Credit full payout back to cash (stake was deducted at placement)
                    payout = bet.amount / bet.price if bet.price and bet.price > 0 else bet.amount
                    portfolio.cash_balance += payout
                    portfolio.total_won += 1
                else:
                    # Loss: stake already deducted at placement, nothing to credit
                    portfolio.total_lost += 1
                portfolio.total_value = portfolio.cash_balance
                portfolio.current_value = portfolio.cash_balance
                portfolio.daily_pnl += bet.pnl

            logger.info(
                f"{'ðŸ†' if result == 'WIN' else 'ðŸ’€'} "
                f"Market {market.id}: {result} | "
                f"Actual={actual:.1f}Â°C, Threshold={market.threshold:.1f}Â°C, "
                f"Side={bet.side}, PnL=${bet.pnl:+.2f}"
            )
            return result

    def _get_actual_weather(self, market) -> float | None:
        """Geçmiş hava verisini çek."""
        try:
            lat, lon = self._get_coords(market.city)
            date_str = market.target_date.strftime("%Y-%m-%d")

            # Open-Meteo archive API
            resp = requests.get(
                "https://archive-api.open-meteo.com/v1/archive",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max,temperature_2m_min",
                    "start_date": date_str,
                    "end_date": date_str,
                    "timezone": "auto",
                },
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            daily = data.get("daily", {})
            metric_map = {
                "temperature_max": "temperature_2m_max",
                "temperature_min": "temperature_2m_min",
                "YES": "temperature_2m_max",
                "NO": "temperature_2m_max",
            }

            api_key = metric_map.get(market.metric, "temperature_2m_max")
            values = daily.get(api_key, [])

            if values and values[0] is not None:
                return values[0]
            return None

        except Exception as e:
            logger.error(f"Gerçek veri çekme hatası: {e}")
            return None

    def _get_coords(self, city: str) -> tuple:
        from scrapers.meteo import MeteoFetcher
        coords = MeteoFetcher.CITY_COORDS.get(city.lower())
        return coords if coords else (40.7128, -74.0060)

    def settle_all(self) -> dict:
        """Tüm bekleyen betleri kontrol et."""
        results = {"win": 0, "loss": 0, "pending": 0}
        with get_session() as session:
            placed_bets = session.query(Bet).filter(
                Bet.status.in_(["placed", "pending", "active"])
            ).all()
            bet_ids = [b.id for b in placed_bets]

        for bid in bet_ids:
            try:
                result = self.check_settlement(bid)
                if result == "WIN":
                    results["win"] += 1
                elif result == "LOSS":
                    results["loss"] += 1
                else:
                    results["pending"] += 1
            except Exception as e:
                logger.error(f"Settlement hatası (bet {bid}): {e}")
                results["pending"] += 1
                continue

        return results


# SettlementEngine kept for complete backwards compatibility
class SettlementEngine:
    """Backward compatible settlement engine wrapper."""

    def __init__(self, db_session, config=None, data_fetcher=None):
        self.db = db_session
        self.config = config
        self.settler = Settler()

    def settle_bet(self, bet, actual_temperature: float) -> dict:
        yes_price = bet.entry_price or 0.5
        strike = bet.strike_temp
        raw_side = (bet.side or "HIGH").upper()
        
        if raw_side in ["YES", "HIGH"]:
            is_win = actual_temperature > strike
        else:
            is_win = actual_temperature < strike
            
        if getattr(bet, "bet_type", "YES") == "NO":
            is_win = not is_win

        if is_win:
            payout = bet.stake * ((1 / yes_price) - 1)
            realized_pnl = payout
            status = "won"
        else:
            realized_pnl = -bet.stake
            status = "lost"

        bet.status = status
        bet.realized_pnl = realized_pnl
        bet.settled_at = datetime.now(timezone.utc).replace(tzinfo=None)
        return {"status": status, "realized_pnl": realized_pnl}

    def update_portfolio_after_settlement(self, portfolio, pnl: float, is_win: bool):
        portfolio.total_realized_pnl += pnl
        if is_win:
            portfolio.total_won += 1
        else:
            portfolio.total_lost += 1
        portfolio.daily_pnl += pnl
        # total_value and current_value are set in the caller based on cash_balance

    async def settle_bets(self):
        results = self.settler.settle_all()
        return results.get("win", 0) + results.get("loss", 0)

    async def update_market_prices(self):
        pass
