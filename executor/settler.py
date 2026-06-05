"""Settlement executor checking forecast against actual weather."""

import json
import logging
import random
from datetime import datetime, timezone
from typing import Dict, Optional
import aiohttp
from database.models import Bet, Market, Portfolio

logger = logging.getLogger("EXECUTOR_SETTLER")


class SettlementEngine:
    """Engine for settling bets against actual weather outcomes."""

    def __init__(self, db_session, config=None, data_fetcher=None):
        self.db = db_session
        self.config = config
        self.data_fetcher = data_fetcher

    def settle_bet(self, bet, actual_temperature: float) -> Dict:
        """Settle bet with actual historical temperature."""
        strike = bet.strike_temp
        bet_type = bet.bet_type  # YES/NO
        raw_side = (bet.side or getattr(bet, "market_type", None) or "HIGH").upper()

        if raw_side in ["YES", "HIGH"]:
            side = "HIGH"
        else:
            side = "LOW"

        if side == "HIGH":
            is_win = actual_temperature > strike
        else:
            is_win = actual_temperature < strike

        if bet_type == "NO":
            is_win = not is_win

        if is_win:
            payout = bet.stake * ((1 / bet.entry_price) - 1)
            realized_pnl = payout
            status = "won"
        else:
            realized_pnl = -bet.stake
            status = "lost"

        result_data = {
            "actual_temperature": actual_temperature,
            "strike": strike,
            "side": side,
            "bet_type": bet_type,
            "is_win": is_win,
            "settled_at": datetime.now(timezone.utc).isoformat(),
        }

        bet.status = status
        bet.realized_pnl = realized_pnl
        bet.result_data = (
            json.dumps(result_data)
            if isinstance(result_data, dict)
            else str(result_data)
        )
        bet.settled_at = datetime.now(timezone.utc)
        return {
            "status": status,
            "realized_pnl": realized_pnl,
            "result_data": result_data,
        }

    def update_portfolio_after_settlement(self, portfolio, pnl: float, is_win: bool):
        """Update portfolio value after a bet is settled."""
        portfolio.total_realized_pnl += pnl
        portfolio.cash_balance += pnl
        portfolio.total_value = (portfolio.total_value or 1000.0) + pnl
        portfolio.current_value = (portfolio.current_value or 1000.0) + pnl

        if is_win:
            portfolio.total_won += 1
        else:
            portfolio.total_lost += 1
        portfolio.daily_pnl += pnl

    def _get_market_for_bet(self, bet):
        """Get associated Market for resolution_date."""
        if not self.db or not getattr(bet, "market_id", None):
            return None
        return self.db.query(Market).filter(Market.market_id == bet.market_id).first()

    async def _fetch_historical_temperature(
        self, city_code: str, latitude: float, longitude: float, target_date: datetime
    ) -> Optional[float]:
        """Fetch actual historical temperature from Open-Meteo archive API."""
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": target_date.strftime("%Y-%m-%d"),
            "end_date": target_date.strftime("%Y-%m-%d"),
            "daily": "temperature_2m_max",
            "timezone": "auto",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        temps = data.get("daily", {}).get("temperature_2m_max", [])
                        if temps and temps[0] is not None:
                            logger.info(
                                "Historical temp for %s on %s: %.1fC",
                                city_code,
                                target_date.strftime("%Y-%m-%d"),
                                temps[0],
                            )
                            return float(temps[0])
                    else:
                        logger.warning(
                            "Open-Meteo archive API returned %s for %s",
                            resp.status,
                            city_code,
                        )
        except Exception:
            logger.exception("Error fetching historical temperature for %s", city_code)
        return None

    async def _get_actual_temperature(self, bet) -> Optional[float]:
        """Get actual temperature from archive or simulation."""
        strike = bet.strike_temp or 25.0
        market = self._get_market_for_bet(bet)
        resolution_date = getattr(market, "resolution_date", None) if market else None

        if resolution_date and resolution_date < datetime.utcnow():
            city_code = getattr(bet, "city_code", None)
            if city_code:
                lat, lon = None, None
                if market:
                    lat = getattr(market, "latitude", None)
                    lon = getattr(market, "longitude", None)
                if lat and lon:
                    actual = await self._fetch_historical_temperature(
                        city_code, lat, lon, resolution_date
                    )
                    if actual is not None:
                        return round(actual, 1)

        try:
            if resolution_date and resolution_date < datetime.utcnow():
                noise = random.gauss(0, 2.5)
            else:
                noise = random.uniform(-3.5, 3.5)
            actual = round(strike + noise, 1)
            logger.info(
                "Using synthetic temperature for %s: %.1fC (no historical data)",
                getattr(bet, "city_code", "?"),
                actual,
            )
            return actual
        except Exception:
            return round(strike + random.gauss(0, 2.8), 1)

    async def settle_bets(self):
        """Scan active bets and settle them securely with localized try-except."""
        if not self.db:
            return 0
        try:
            active_bets = (
                self.db.query(Bet).filter(Bet.status.in_(["active", "open"])).all()
            )
            settled_count = 0
            now = datetime.utcnow()
            for bet in active_bets:
                try:
                    market = self._get_market_for_bet(bet)
                    if not market or not market.resolution_date:
                        continue
                    if market.resolution_date > now:
                        continue
                    actual_temp = await self._get_actual_temperature(bet)
                    if actual_temp is None:
                        continue
                    result = self.settle_bet(bet, actual_temp)

                    portfolio = self.db.query(Portfolio).filter(Portfolio.id == 1).first()
                    if portfolio:
                        is_win = result["status"] == "won"
                        self.update_portfolio_after_settlement(
                            portfolio, result["realized_pnl"], is_win
                        )
                    self.db.commit()
                    settled_count += 1
                except Exception as e:
                    logger.error("Error settling bet %s: %s", bet.id, e, exc_info=True)
                    if self.db:
                        self.db.rollback()
            return settled_count
        except Exception as e:
            logger.error("Settlement error: %s", e)
            if self.db:
                self.db.rollback()
            return 0

    async def update_market_prices(self):
        """Simulate live changes in market prices."""
        if not self.db:
            return
        try:
            markets = self.db.query(Market).filter(Market.status == "active").all()
            for m in markets:
                variation = random.uniform(-0.02, 0.02)
                if m.current_yes_bid:
                    m.current_yes_bid = max(0.01, min(0.99, m.current_yes_bid + variation))
                    m.current_no_bid = max(0.01, min(0.99, 1 - m.current_yes_bid))
                m.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            if markets:
                logger.info("[PRICES] %d market prices updated", len(markets))
            self._simulate_ladder_fills(markets)
        except Exception as e:
            logger.error("Price update error: %s", e)
            if self.db:
                self.db.rollback()

    def _simulate_ladder_fills(self, markets):
        """Simulate ladder fill operations."""
        try:
            active_bets = (
                self.db.query(Bet).filter(Bet.status.in_(["active", "open"])).all()
            )
            for bet in active_bets:
                ladder = []
                if bet.ladder_data:
                    try:
                        ladder = json.loads(bet.ladder_data)
                    except Exception:
                        continue
                if not ladder or not isinstance(ladder, list):
                    continue
                current_price = None
                for m in markets:
                    if m.market_id == bet.market_id or m.city_code == bet.city_code:
                        current_price = m.current_yes_bid
                        break
                if current_price is None:
                    continue
                filled = False
                for order in ladder:
                    level_price = order.get("price", 0)
                    if current_price <= level_price:
                        bet.stake_amount = bet.stake_amount or bet.stake
                        bet.entry_price = level_price
                        bet.current_price = current_price
                        bet.unrealized_pnl = (
                            (bet.stake_amount or 0)
                            * (1 / level_price - 1)
                            * (1 if bet.outcome == "YES" else -1)
                        )
                        filled = True
                        logger.info(
                            "[LADDER FILL] %s filled @ %s (current %s)",
                            bet.city,
                            level_price,
                            current_price,
                        )
                if filled:
                    self.db.commit()
        except Exception as e:
            logger.error("Ladder fill sim error: %s", e)
class MockFetcher:
    """Mock weather fetcher for test script."""
    def get_city_coords(self, city_code: str):
        return (32.8471, -96.8517)
