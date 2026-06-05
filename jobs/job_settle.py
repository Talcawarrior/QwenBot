"""Job for checking and settling past bets."""

import logging
from executor.settler import SettlementEngine
from database.db import get_db_session

logger = logging.getLogger("JOB_SETTLE")


async def run():
    """Settle resolved/past bets."""
    db = get_db_session()
    se = SettlementEngine(db)
    try:
        logger.info("Running settlement loop...")
        count = await se.settle_bets()
        await se.update_market_prices()
        return count
    finally:
        db.close()
