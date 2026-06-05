"""Job for analyzing markets and making trade decisions."""

import logging
from engine.strategy import BettingEngine
from engine.calculator import WeatherEngine
from database.db import get_db_session

logger = logging.getLogger("JOB_ANALYZE")


async def run(market, portfolio_value, forecast=None):
    """Analyze a market using our forecasting calculator and strategy engine."""
    db = get_db_session()
    we = WeatherEngine()
    be = BettingEngine(db_session=db, weather_engine=we)
    try:
        logger.info("Analyzing market: %s", getattr(market, "id", ""))
        signal = await be.analyze_market(market, portfolio_value, forecast)
        return signal
    finally:
        db.close()
        await we.stop()
