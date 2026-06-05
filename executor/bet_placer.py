"""Bet placement executor."""

import logging
from database.models import Bet

logger = logging.getLogger("EXECUTOR_BET_PLACER")


class BetPlacer:
    """Executes trades on the database / paper trade mode."""

    def __init__(self, db_session=None):
        self.db = db_session

    def place_paper_bet(self, bet_record: Bet) -> bool:
        """Saves paper/simulated trade to SQLite."""
        if not self.db:
            return False
        try:
            self.db.add(bet_record)
            self.db.commit()
            return True
        except Exception:
            logger.exception("Error inserting paper bet")
            if self.db:
                self.db.rollback()
            return False
