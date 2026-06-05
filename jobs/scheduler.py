"""Independent scheduled job executors."""

import logging
from database.db import get_session
from database.models import Bet, WeatherMarket

logger = logging.getLogger("JOBS_SCHEDULER")


def run_fetch_markets():
    """Fetch markets from Polymarket and save to raw weather_markets."""
    from scrapers.polymarket import PolymarketScraper
    scraper = PolymarketScraper()
    count = scraper.fetch_and_save()
    return f"{count} market çekildi ve kaydedildi"


def run_parse_markets():
    """Parse raw weather_markets to extract structured fields."""
    from engine.market_parser import MarketParser
    parser = MarketParser()
    count = parser.parse_all_unparsed()
    return f"{count} market parse edildi"


def run_fetch_weather():
    """Fetch forecast values for parsed weather_markets."""
    from scrapers.meteo import MeteoFetcher
    fetcher = MeteoFetcher()
    count = fetcher.fetch_all_markets()
    return f"{count} hava tahmini çekildi ve kaydedildi"


def run_analyze():
    """Run forecast analyses for open markets."""
    from engine.calculator import Calculator
    calc = Calculator()
    analyzed = 0
    with get_session() as session:
        markets = session.query(WeatherMarket).filter(
            WeatherMarket.status == "open",
            WeatherMarket.city.isnot(None),
        ).all()
        market_ids = [m.id for m in markets]

    for mid in market_ids:
        try:
            calc.analyze_market(mid)
            analyzed += 1
        except Exception as e:
            logger.error(f"Analiz hatası {mid}: {e}")
            continue

    return f"{analyzed} market analiz edildi ve kaydedildi"


def run_place_bets():
    """Execute betting strategy and place live/paper bets."""
    from executor.bet_placer import BetPlacer
    placer = BetPlacer()
    count = placer.place_all_pending()
    return f"{count} adet yeni bet açıldı"


def run_settle():
    """Settle resolved bets against actual weather data."""
    from executor.settler import Settler
    settler = Settler()
    results = settler.settle_all()
    return f"Sonuçlandırılan -> Kazanan:{results['win']}, Kaybeden:{results['loss']}, Bekleyen:{results['pending']}"


def run_report():
    """Print daily consolidated PnL and trade report."""
    with get_session() as session:
        total_bets = session.query(Bet).count()
        won = session.query(Bet).filter(Bet.status == "won").count()
        lost = session.query(Bet).filter(Bet.status == "lost").count()
        open_markets = session.query(WeatherMarket).filter(
            WeatherMarket.status == "open"
        ).count()

        from sqlalchemy import func
        total_pnl = session.query(func.sum(Bet.pnl)).scalar() or 0.0

        report = (
            f"\n📊 GÜNLÜK CONSOLIDATED RAPOR\n"
            f"  Açık Marketler: {open_markets}\n"
            f"  Toplam Bahis: {total_bets}\n"
            f"  Kazanılan: {won} | Kaybedilen: {lost}\n"
            f"  Net PnL: ${total_pnl:+.2f}\n"
        )
        logger.info(report)
        return report


def start_scheduler():
    """Mock/stub for cron scheduler activation."""
    logger.info("Scheduler initialized in background thread...")
