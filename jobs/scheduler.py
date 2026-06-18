"""Independent scheduled job executors."""

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import func

from database.db import get_session
from database.models import OPEN_BET_STATUSES, Analysis, Bet, Portfolio, WeatherMarket

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
        markets = (
            session.query(WeatherMarket)
            .filter(
                WeatherMarket.status == "open",
                WeatherMarket.city.isnot(None),
                WeatherMarket.target_date > datetime.now(UTC).replace(tzinfo=None),
            )
            .all()
        )
        market_ids = [m.id for m in markets]

    for mid in market_ids:
        try:
            result = calc.analyze_market(mid)
            if result is not None:
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
    """
    Refresh `current_price`, fill ladder orders, and update `unrealized_pnl`
    on every open bet. Updates Portfolio.total_value at the end.

    Algorithm:
        1. Query every Bet in an open status.
        2. For each bet, look up the latest market price (WeatherMarket.yes_price).
        3. Update Bet.current_price, recompute unrealized_pnl.
        4. Check ladder_data: if any pending rung's trigger price is reached,
           mark it "filled" and debit the rung amount from portfolio cash.
        5. Update Portfolio.total_value = cash + open_exposure + unrealized_pnl.
    """
    open_statuses = OPEN_BET_STATUSES
    updated = 0
    with get_session() as session:
        bets = session.query(Bet).filter(Bet.status.in_(open_statuses)).all()

        # Pre-fetch price map: market_id -> prices
        market_ids = list(set(b.market_id for b in bets if b.market_id))
        price_map = {}
        if market_ids:
            markets = session.query(WeatherMarket).filter(WeatherMarket.id.in_(market_ids)).all()
            for m in markets:
                price_map[m.id] = {
                    "yes": float(m.yes_price) if m.yes_price is not None else 0.5,
                    "no": float(m.no_price) if m.no_price is not None else 0.5,
                }

        total_unrealized = 0.0

        for bet in bets:
            if bet.market_id not in price_map:
                continue

            prices = price_map[bet.market_id]

            # current_price from market
            if bet.side and bet.side.upper() == "NO":
                current = max(0.0, min(1.0, 1.0 - prices["yes"]))
            else:
                current = max(0.0, min(1.0, prices["yes"]))

            entry = float(bet.entry_price or bet.price or 0.0)
            shares = float(bet.shares or 0.0)

            bet.current_price = current

            # 1. unrealized_pnl
            # current_price is already in side terms (YES=yes_price, NO=no_price)
            # so the same (current - entry) * shares formula works for both sides.
            bet.unrealized_pnl = round(shares * (current - entry), 2)

            total_unrealized += bet.unrealized_pnl or 0.0

            # 2. Ladder fill check — only status=="pending" rungs fill.
            # L1 is already "filled" at open (bet_placer), so safe from double-debit.
            from utils.accounting import debit_stake

            if bet.ladder_data:
                try:
                    ladder = json.loads(bet.ladder_data) if isinstance(bet.ladder_data, str) else bet.ladder_data
                    if isinstance(ladder, list):
                        filled_amount = 0.0
                        for rung in ladder:
                            if rung.get("status") == "pending":
                                trigger_price = float(rung.get("price", 0))
                                rung_size = float(rung.get("size", rung.get("amount", 0)))
                                if bet.side and bet.side.upper() == "NO":
                                    # NO side: fill when current NO price (1 - yes_price) <= trigger_price
                                    should_fill = (1.0 - current) <= trigger_price
                                else:
                                    should_fill = current <= trigger_price
                                if should_fill and rung_size > 0:
                                    rung["status"] = "filled"
                                    rung["filled_at"] = datetime.now(UTC).isoformat()
                                    filled_amount += rung_size
                        if filled_amount > 0:
                            bet.ladder_data = json.dumps(ladder)
                            debit_stake(session, filled_amount, f"ladder_fill:{bet.market_id}")
                except Exception as e:
                    logger.warning("Ladder parse hatası %s: %s", bet.id, e)

            updated += 1
            session.add(bet)

        # 3. Portfolio: conservative current = cash + open_exposure
        # Unrealized PnL is paper money — don't bake it into total_value.
        portfolio = session.query(Portfolio).filter(Portfolio.id == 1).first()
        if portfolio:
            realized_pnl_total = (
                session.query(func.coalesce(func.sum(Bet.pnl), 0.0)).filter(Bet.status.in_(("won", "lost"))).scalar()
            ) or 0.0
            open_exposure = (
                session.query(func.coalesce(func.sum(Bet.amount), 0.0))
                .filter(Bet.status.in_(OPEN_BET_STATUSES))
                .scalar()
            ) or 0.0
            # Conservative: cash + money locked in bets
            if portfolio.cash_balance is not None:
                cash = float(portfolio.cash_balance)
            else:
                cash = (portfolio.initial_value or 1000.0) + float(realized_pnl_total)
            portfolio.total_value = round(cash + float(open_exposure), 2)
            portfolio.current_value = portfolio.total_value  # Sync current_value
            portfolio.last_updated = datetime.now(UTC).replace(tzinfo=None)
            session.add(portfolio)

        session.commit()
    return f"{updated} açık bet güncellendi, total_unrealized={total_unrealized:.2f}"


def run_settle():
    """Settle resolved bets against actual weather data."""
    from executor.settler import SettlementEngine

    engine = SettlementEngine()
    results = engine.settle_all()
    return f"Sonuçlandırılan -> Kazanan:{results['win']}, Kaybeden:{results['loss']}, Bekleyen:{results['pending']}"


def run_report():
    """Print daily consolidated PnL and trade report."""
    with get_session() as session:
        total_bets = session.query(Bet).count()
        won = session.query(Bet).filter(Bet.status == "won").count()
        lost = session.query(Bet).filter(Bet.status == "lost").count()
        open_markets = session.query(WeatherMarket).filter(WeatherMarket.status == "open").count()

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


def run_risk_management():
    """Aktif risk yönetimi: stop-loss, take-profit, time-decay, trailing stop kontrolleri.

    Her açık bahsi tara, RiskManager.check_early_exit ile kontrol et,
    erken çıkılması gereken pozisyonları kapat.
    """
    from config.settings import bot_config
    from engine.strategy import RiskManager

    with get_session() as session:
        rm = RiskManager(db_session=session, cfg=bot_config)
        bets = session.query(Bet).filter(Bet.status.in_(OPEN_BET_STATUSES)).all()

        if not bets:
            return "Risk: no open positions"

        # Pre-fetch market prices
        market_ids = list(set(b.market_id for b in bets if b.market_id))
        markets = {}
        if market_ids:
            for m in session.query(WeatherMarket).filter(WeatherMarket.id.in_(market_ids)).all():
                markets[m.id] = m

        closed_count = 0
        for bet in bets:
            market = markets.get(bet.market_id)
            if not market:
                continue

            # Current price in side terms
            yes_price = float(market.yes_price or 0.5)
            if bet.side and bet.side.upper() == "NO":
                current_price = max(0.0, min(1.0, 1.0 - yes_price))
            else:
                current_price = max(0.0, min(1.0, yes_price))

            # Check early exit
            should_exit, reason = rm.check_early_exit(bet, current_price, market)

            # Check model reversal if analysis exists
            if not should_exit:
                analysis = (
                    session.query(Analysis)
                    .filter(Analysis.market_id == bet.market_id)
                    .order_by(Analysis.analyzed_at.desc())
                    .first()
                )
                rev_exit, rev_reason = rm.check_model_reversal(bet, analysis)
                if rev_exit:
                    should_exit, reason = True, rev_reason

            if should_exit:
                from utils.accounting import credit_sale

                # Calculate proceeds: for ladder bets, sum ONLY filled rungs
                entry = float(bet.entry_price or bet.price or 0.0)
                shares = float(bet.shares or 0.0)
                realized = round(shares * (current_price - entry), 2)
                proceeds = round(shares * current_price, 2)  # principal + PnL

                # Ladder: only filled rungs were debited, so only filled
                # rung shares can be sold.  Pending rungs are cancelled.
                if bet.ladder_data:
                    try:
                        ladder = json.loads(bet.ladder_data) if isinstance(bet.ladder_data, str) else bet.ladder_data
                        if isinstance(ladder, list):
                            filled_shares = sum(
                                float(r.get("shares", r.get("size", r.get("amount", 0))))
                                for r in ladder
                                if r.get("status") == "filled"
                            )
                            if filled_shares > 0:
                                proceeds = round(filled_shares * current_price, 2)
                                realized = round(filled_shares * (current_price - entry), 2)
                    except Exception:
                        pass  # fall back to simple calculation

                bet.status = "closed_early"
                bet.close_reason = reason
                bet.closed_at = datetime.now(UTC)
                bet.realized_pnl = realized
                bet.pnl = realized
                bet.current_price = current_price

                # Credit proceeds to cash via central accounting.
                # After credit_sale, cash_balance already includes proceeds.
                # total_value = cash_balance (bet is closed, no unrealized PnL).
                credit_sale(session, proceeds, f"early_exit:{bet.market_id}:{reason}")

                portfolio = session.query(Portfolio).filter(Portfolio.id == 1).first()
                if portfolio:
                    portfolio.total_value = round(portfolio.cash_balance or 0.0, 2)
                    portfolio.last_updated = datetime.now(UTC)

                session.add(bet)
                session.add(portfolio) if portfolio else None
                closed_count += 1
                logger.info(
                    "Early exit bet=%s market=%s reason=%s realized=$%.2f proceeds=$%.2f",
                    bet.id,
                    bet.market_id,
                    reason,
                    realized,
                    proceeds,
                )

        session.commit()
        return f"Risk: {closed_count} position(s) closed early"


def start_scheduler():
    """Mock/stub for cron scheduler activation."""
    logger.info("Scheduler initialized in background thread...")
