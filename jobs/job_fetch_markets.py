"""Job for fetching daily-temperature markets from Polymarket."""

import logging
from scrapers.polymarket import PolymarketScraper
from database.db import get_db_session
from database.models import Market
from datetime import datetime

logger = logging.getLogger("JOB_FETCH_MARKETS")


async def run():
    """Fetch and save active Polymarket events."""
    scraper = PolymarketScraper()
    try:
        logger.info("Fetching markets from Polymarket...")
        markets = await scraper.fetch_polymarket_events()
        if not markets:
            logger.info("No markets fetched.")
            return 0

        # Filter out past/expired markets safely
        now = datetime.utcnow()
        filtered_markets = []
        for m in markets:
            res_date = m.get("resolution_date")
            if res_date is None:
                filtered_markets.append(m)
                continue
            if res_date.tzinfo is not None:
                res_date = res_date.replace(tzinfo=None)
            if res_date >= now:
                filtered_markets.append(m)
        markets = filtered_markets

        db = get_db_session()
        saved = 0
        for m in markets[:50]:
            try:
                existing = db.query(Market).filter(Market.market_id == m.get("market_id")).first()
                if existing:
                    existing.yes_price = m.get("yes_price", 0.5)
                    existing.no_price = m.get("no_price", 0.5)
                    existing.current_yes_bid = m.get("current_yes_bid", 0.5)
                    existing.current_no_bid = m.get("current_no_bid", 0.5)
                    existing.volume = m.get("volume", 0.0)
                    existing.status = "active"
                else:
                    new_market = Market(
                        market_id=m.get("market_id", ""),
                        event_id=m.get("event_id", ""),
                        city=m.get("city", "Unknown"),
                        city_code=m.get("city_code", ""),
                        outcome_type=m.get("outcome_type", "YES"),
                        strike_temp=m.get("strike_temp", 80.0),
                        date=m.get("resolution_date"),
                        resolution_date=m.get("resolution_date"),
                        yes_price=m.get("yes_price", 0.5),
                        no_price=m.get("no_price", 0.5),
                        current_yes_bid=m.get("current_yes_bid", 0.5),
                        current_no_bid=m.get("current_no_bid", 0.5),
                        volume=m.get("volume", 0.0),
                        range_type=m.get("market_type", "HIGH"),
                        status="active",
                    )
                    db.add(new_market)
                db.commit()
                saved += 1
            except Exception as e:
                db.rollback()
                logger.error("Error saving market %s: %s", m.get("city"), e)

        db.close()
        logger.info("Successfully fetched and processed %d markets", saved)
        return saved
    finally:
        await scraper.close_session()
