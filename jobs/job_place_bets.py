"""Job for executing betting signals on the database."""

import logging
from engine.strategy import BettingEngine
from database.db import get_db_session

logger = logging.getLogger("JOB_PLACE_BETS")


async def run(signal, market):
    """Place a paper bet on the database."""
    db = get_db_session()
    be = BettingEngine(db_session=db)
    try:
        logger.info("Executing betting signal for city: %s", getattr(signal, "city", ""))
        bet = await be.execute_signal(signal, market)
        return bet
    finally:
        db.close()
