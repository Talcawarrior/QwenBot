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


def run_update_prices():
    """Refresh `current_price` (and `unrealized_pnl`) on every open bet.

    The Bet row is created with `current_price = entry_price` (no
    market movement yet). The settler updates current_price only at
    settlement time, which means PnL stays at 0 for the entire
    active position lifetime — misleading on the dashboard and
    impossible to use for risk management. Run this on every scan
    cycle so the dashboard reflects live price movement.

    Algorithm:
        For every Bet in an open status, look up the latest YES
        price of the underlying market, set Bet.current_price to it,
        and recompute unrealized_pnl = (current - entry) * shares.
        Uses the market_id and the side (YES/NO) to pick the right
        price: YES -> yes_price, NO -> 1 - yes_price.
    """
    open_statuses = ("active", "open", "placed", "pending")
    updated = 0
    with get_session() as session:
        bets = (
            session.query(Bet)
            .filter(Bet.status.in_(open_statuses))
            .all()
        )
        for bet in bets:
            market = session.query(WeatherMarket).filter(
                WeatherMarket.id == bet.market_id
            ).first()
            if not market or market.yes_price is None:
                continue
            yes_price = float(market.yes_price)
            if bet.side and bet.side.upper() == "NO":
                current = max(0.0, min(1.0, 1.0 - yes_price))
            else:
                current = max(0.0, min(1.0, yes_price))
            entry = float(bet.entry_price or bet.price or 0.0)
            shares = float(bet.shares or 0.0)
            bet.current_price = current
            bet.unrealized_pnl = (current - entry) * shares
            # bet.pnl is "realized" — leave it alone. The dashboard
            # shows unrealized_pnl, so the live number is what changes.
            updated += 1
        session.commit()
    return f"{updated} açık bet'in current_price/unrealized_pnl güncellendi"


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
