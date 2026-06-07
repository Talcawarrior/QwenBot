"""
MAIN SERVER - FastAPI + WebSocket + Command Line Interface (CLI)
- Fully decoupled, modular and robust
- Handles CLI tasks (e.g. python main.py fetch) for pinpoint, isolated executions
- Runs the FastAPI live server and WebSocket dashboard on 'python main.py run'
"""

import os
import argparse
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

# Package Imports
from config.settings import config
from config.logging_config import setup_logging
from database.db import init_db, get_db_session, get_db_session_factory
from database.models import Portfolio, WeatherMarket, Bet, Analysis
from engine.strategy import RiskManager, BettingEngine, SIALoop
from engine.calculator import WeatherEngine
from executor.settler import SettlementEngine
from scrapers.polymarket import PolymarketScraper

setup_logging()
logger = logging.getLogger(__name__)


# Global State tracking for FastAPI Web App
class BotState:
    """Global bot state tracking running status, modules, and tasks."""

    def __init__(self):
        self.is_running = False
        self.locked = False
        self.lock_reason = None
        self.last_scan = None
        self.total_signals = 0
        self.total_bets = 0
        self.websocket_clients: List[WebSocket] = []
        self.tasks = {}
        self.start_stop_lock = asyncio.Lock()

        # Config reference
        self.config = config
        self.db_session_factory = None
        self.data_fetcher = None
        self.weather_engine = None
        self.risk_manager = None
        self.betting_engine = None
        self.settlement_engine = None
        self.sia_loop = None

    def initialize_modules(self):
        """Initialize all modular components."""
        self.db_session_factory = get_db_session_factory()
        self.data_fetcher = PolymarketScraper()
        self.weather_engine = WeatherEngine(self.db_session_factory, self.config)
        self.risk_manager = RiskManager(None, self.config)
        self.betting_engine = BettingEngine(
            None, self.risk_manager, self.weather_engine
        )
        self.settlement_engine = SettlementEngine(None, self.config)
        self.sia_loop = SIALoop(self.db_session_factory, self.config)


state = BotState()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Lifespan context manager for startup and shutdown."""
    logger.info("PolyMarket Ultimate Weather Bot starting...")
    init_db()
    state.initialize_modules()

    # Ensure initial portfolio row exists in DB
    try:
        db = get_db_session()
        try:
            portfolio = db.query(Portfolio).filter(Portfolio.id == 1).first()
            if not portfolio:
                portfolio = Portfolio(
                    id=1,
                    initial_value=state.config.INITIAL_PORTFOLIO,
                    current_value=state.config.INITIAL_PORTFOLIO,
                    cash_balance=state.config.INITIAL_PORTFOLIO,
                    total_value=state.config.INITIAL_PORTFOLIO,
                    total_realized_pnl=0.0,
                )
                db.add(portfolio)
                db.commit()
                logger.info("Initial portfolio row created in DB")
        finally:
            db.close()
    except Exception as e:
        logger.warning("Portfolio init warning: %s", e)

    logger.info("Database and all modules ready.")
    logger.info("POLYMARKET ULTIMATE HYBRID WEATHER BOT v4.0")
    yield

    # Shutdown
    logger.info("Bot shutting down...")
    if state.tasks:
        for task in list(state.tasks.values()):
            if not task.done():
                task.cancel()
        await asyncio.gather(*state.tasks.values(), return_exceptions=True)
        state.tasks.clear()


app = FastAPI(title="PolyMarket Ultimate Weather Bot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


async def broadcast_message(message: dict):
    """Broadcast message to all connected WebSocket clients."""
    if not state.websocket_clients:
        return
    disconnected = []
    for client in state.websocket_clients:
        try:
            await client.send_json(message)
        except Exception:
            disconnected.append(client)
    for client in disconnected:
        if client in state.websocket_clients:
            state.websocket_clients.remove(client)


@app.get("/")
async def root():
    """Serve HTML Dashboard"""
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    if os.path.exists(dashboard_path):
        return FileResponse(dashboard_path)
    return HTMLResponse("<h1>Dashboard yükleniyor...</h1>")


@app.get("/api/status")
async def get_status():
    """Get bot status and metrics."""
    from database.models import Bet, Analysis
    from sqlalchemy import func
    db = get_db_session()
    try:
        portfolio = db.query(Portfolio).filter(Portfolio.id == 1).first()
        daily_pnl = state.risk_manager.get_daily_pnl() if state.risk_manager else 0.0

        # Read live counts and exposure from DB so the dashboard doesn't
        # drift from reality. `placed` is the actual status used by
        # BetPlacer; include all open-style states (active, open, placed,
        # pending) so exposure/totals stay consistent even if statuses
        # evolve. We bypass RiskManager.get_total_exposure() because it
        # is initialized with `db=None` and only knows about the in-memory
        # city_bet_counts dict (which the scheduler never updates).
        open_statuses = ("active", "open", "placed", "pending")
        total_bets_db = (
            db.query(Bet)
            .filter(Bet.status.in_(open_statuses))
            .count()
        )
        total_signals_db = (
            db.query(Analysis)
            .filter(Analysis.should_bet.is_(True))
            .count()
        )
        exposure_db = (
            db.query(func.coalesce(func.sum(Bet.amount), 0.0))
            .filter(Bet.status.in_(open_statuses))
            .scalar()
        ) or 0.0

        # Live unrealized PNL across all open bets. The dashboard
        # `daily_pnl` field is realised-only (set by the settler when a
        # bet actually settles), so on a bot with active open positions
        # the header shows $0 even though the portfolio is up $180+.
        # Surface the unrealized total separately so the user can see
        # the actual PnL of their open book.
        unrealized_pnl_db = (
            db.query(func.coalesce(func.sum(Bet.unrealized_pnl), 0.0))
            .filter(Bet.status.in_(open_statuses))
            .scalar()
        ) or 0.0
        realized_pnl_db = (
            db.query(func.coalesce(func.sum(Bet.pnl), 0.0))
            .filter(Bet.status.in_(open_statuses))
            .scalar()
        ) or 0.0

        return {
            "is_running": state.is_running,
            "locked": state.locked,
            "lock_reason": state.lock_reason,
            "portfolio": {
                "initial": state.config.INITIAL_PORTFOLIO,
                "current": portfolio.total_value if portfolio else state.config.INITIAL_PORTFOLIO,
                "daily_pnl": daily_pnl,
                "unrealized_pnl": float(unrealized_pnl_db),
                "realized_pnl": float(realized_pnl_db),
                "total_pnl": float(unrealized_pnl_db) + float(realized_pnl_db),
                "exposure": float(exposure_db),
                "smart_pool": state.config.INITIAL_PORTFOLIO * state.config.SMART_POOL_PCT,
            },
            "stats": {
                "total_signals": total_signals_db,
                "total_bets": total_bets_db,
                "last_scan": state.last_scan.isoformat() if state.last_scan else None,
            },
            "limits": {
                "max_bet_pct": state.config.MAX_BET_PCT * 100,
                "max_exposure_pct": state.config.TOTAL_EXPOSURE_PCT * 100,
                "daily_stop_loss_pct": state.config.DAILY_LOSS_LIMIT * 100,
                "city_cap": state.config.CITY_CAP,
            },
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()


@app.get("/api/signals")
async def get_signals():
    """Get active signals and bets with Ladder details.

    Edge semantics (UX fix #6):
    - ``entry_edge``   = the edge that triggered the bet
                         (model_prob_at_entry − market_price_at_entry),
                         taken from the originating Analysis row.
    - ``live_edge``    = current "would I enter at today's price?" edge
                         (model_prob_now − current_price), kept under
                         the legacy ``edge`` key for backward compat.
    - ``move_pct``     = (current − entry) / entry, signed — useful at
                         a glance to see how much the price has run
                         since entry. Positive = good for a YES bet.
    For a freshly placed bet the entry_edge explains why we bought;
    for a held bet the live_edge is the "still a good trade?" signal.
    """
    db = get_db_session()
    try:
        active_bets = db.query(Bet).filter(Bet.status.in_(["active", "open", "placed", "pending"])).all()
        signals = []
        for bet in active_bets:
            market = db.query(WeatherMarket).filter(WeatherMarket.id == bet.market_id).first()
            res_date = market.target_date if market else None
            # entry_price and current_price are now the canonical columns
            # written by place_bet. fall back to legacy `price` only for
            # back-compat with rows that pre-date the fix.
            entry = bet.entry_price if bet.entry_price is not None else bet.price
            current = bet.current_price if bet.current_price is not None else bet.entry_price
            entry = float(entry) if entry is not None else None
            current = float(current) if current is not None else None
            # Real fair value from cached analysis if available; else skip
            fair_value = None
            live_edge = None
            entry_edge = None
            move_pct = None
            try:
                from database.models import Analysis
                # Latest analysis (live "should I enter now?" signal)
                latest = (
                    db.query(Analysis)
                    .filter(Analysis.market_id == bet.market_id)
                    .order_by(Analysis.analyzed_at.desc())
                    .first()
                )
                if latest is not None:
                    fair_value = float(latest.estimated_probability)
                    if current is not None:
                        live_edge = fair_value - current

                # Originating analysis (the one that triggered this bet).
                # Falls back to the latest if analysis_id is missing.
                if bet.analysis_id is not None:
                    origin = (
                        db.query(Analysis)
                        .filter(Analysis.id == bet.analysis_id)
                        .first()
                    )
                else:
                    origin = None
                if origin is not None and origin.edge is not None:
                    entry_edge = float(origin.edge)

                # Move % since entry — derived directly from prices so
                # the UI can show price momentum even without an analysis
                # row present.
                if entry is not None and current is not None and entry > 0:
                    move_pct = (current - entry) / entry
            except Exception:
                pass
            signals.append(
                {
                    "id": bet.id,
                    "market_id": bet.market_id,
                    "city": bet.city or (market.city if market else "Unknown"),
                    "outcome": bet.side if bet.side else (bet.outcome or "YES"),
                    "entry_price": entry,
                    "current_price": current,
                    "stake_amount": bet.amount if bet.amount is not None else bet.stake_amount,
                    "unrealized_pnl": (
                        float(bet.unrealized_pnl) if bet.unrealized_pnl is not None else 0.0
                    ),
                    "fair_value": fair_value,
                    "edge": live_edge,        # legacy key — now means "live edge"
                    "entry_edge": entry_edge, # UX fix #6: edge at the time of entry
                    "live_edge": live_edge,   # explicit alias for clarity
                    "move_pct": move_pct,     # UX fix #6: (current − entry) / entry
                    "ladder_orders": [],
                    "placed_at": bet.placed_at.isoformat() if bet.placed_at else None,
                    "resolution_date": res_date.isoformat() if res_date else None,
                    "status": bet.status if bet.status else "UNKNOWN",
                }
            )
        return {"signals": signals, "count": len(signals)}
    except Exception as e:
        logger.error("Error in get_signals API: %s", e, exc_info=True)
        return {"error": str(e), "signals": [], "count": 0}
    finally:
        db.close()


@app.get("/api/markets")
async def get_markets():
    """Get all future active weather markets (Global Market Watch) — today + 2 days only."""
    from datetime import timedelta
    from engine.calculator import Calculator
    from database.models import WeatherForecast
    db = get_db_session()
    try:
        now = datetime.utcnow()
        upper = now + timedelta(days=2)
        markets = (
            db.query(WeatherMarket)
            .filter(
                WeatherMarket.target_date >= now,
                WeatherMarket.target_date <= upper,
                WeatherMarket.status == "open",
            )
            .limit(100)
            .all()
        )
        market_list = []
        calc = Calculator()

        for m in markets:
            # Skip markets missing essential data (no hardcoded fallbacks)
            if m.yes_price is None or m.threshold is None or not m.city:
                continue
            current_price = float(m.yes_price)

            # Real model probability from cached WeatherForecast rows (DB-side)
            model_prob = current_price
            try:
                if m.metric in ("temperature_max", "temperature_min"):
                    forecasts = (
                        db.query(WeatherForecast)
                        .filter(
                            WeatherForecast.market_id == m.id,
                            WeatherForecast.metric == m.metric,
                        )
                        .order_by(WeatherForecast.fetched_at.desc())
                        .limit(8)
                        .all()
                    )
                    latest_by_source = {}
                    for f in forecasts:
                        if f.source not in latest_by_source:
                            latest_by_source[f.source] = f.predicted_value
                    forecast_values = list(latest_by_source.values())
                    if forecast_values and m.target_date:
                        days_ahead = max(
                            (m.target_date - now).days, 1
                        )
                        model_prob = calc.estimate_probability(
                            forecast_values,
                            float(m.threshold),
                            days_ahead,
                        )
            except Exception:
                model_prob = current_price

            edge = model_prob - current_price
            ev = (
                (model_prob * (1 / current_price - 1)) - (1 - model_prob)
                if current_price > 0
                else 0.0
            )

            market_list.append(
                {
                    "id": m.id,
                    "city": m.city,
                    "city_code": m.city_code or "",
                    "date": m.target_date.isoformat() if m.target_date else None,
                    "outcome_type": m.metric or "YES",
                    "strike_temp": float(m.threshold),
                    "current_yes_bid": current_price,
                    "current_no_bid": (
                        m.no_price
                        if m.no_price is not None
                        else (1 - current_price)
                    ),
                    "model_prob": model_prob,
                    "edge": edge,
                    "ev": ev,
                    "volume": m.volume or 0,
                }
            )
        return {"markets": market_list, "count": len(market_list)}
    except Exception as e:
        return {"error": str(e), "markets": []}
    finally:
        db.close()


@app.get("/api/history")
async def get_history():
    """Get settled won/lost bet history."""
    db = get_db_session()
    try:
        settled_bets = (
            db.query(Bet)
            .filter(Bet.status.in_(["settled", "won", "lost"]))
            .order_by(Bet.settled_at.desc())
            .limit(50)
            .all()
        )

        history = []
        total_won = 0
        total_lost = 0

        for bet in settled_bets:
            if bet.pnl > 0:
                total_won += 1
            else:
                total_lost += 1

            history.append(
                {
                    "id": bet.id,
                    "city": bet.city,
                    "outcome": bet.side if bet.side else "YES",
                    "entry_price": bet.price,
                    "stake_amount": bet.amount,
                    "realized_pnl": bet.pnl or 0.0,
                    "result": "WIN" if bet.pnl > 0 else "LOSS",
                    "settled_at": bet.settled_at.isoformat() if bet.settled_at else None,
                }
            )

        win_rate = (total_won / (total_won + total_lost) * 100) if (total_won + total_lost) > 0 else 0
        return {
            "history": history,
            "stats": {
                "total_won": total_won,
                "total_lost": total_lost,
                "win_rate": round(win_rate, 2),
            },
        }
    except Exception as e:
        return {"error": str(e), "history": []}
    finally:
        db.close()


@app.post("/api/start")
async def start_bot():
    """Start the background loops."""
    async with state.start_stop_lock:
        if state.is_running:
            return {"status": "already_running"}

        state.is_running = True
        state.locked = False
        state.lock_reason = None

        state.tasks["scan_and_bet"] = asyncio.create_task(scan_and_bet_loop(), name="scan_and_bet_loop")
        state.tasks["settlement"] = asyncio.create_task(settlement_loop(), name="settlement_loop")

        await broadcast_message({"type": "bot_started", "timestamp": datetime.now().isoformat()})
        return {"status": "started", "message": "Bot başlatıldı"}


@app.post("/api/stop")
async def stop_bot():
    """Stop the background loops."""
    async with state.start_stop_lock:
        state.is_running = False
        for task in list(state.tasks.values()):
            if not task.done():
                task.cancel()
        if state.tasks:
            await asyncio.gather(*state.tasks.values(), return_exceptions=True)
        state.tasks.clear()
        await broadcast_message({"type": "bot_stopped", "timestamp": datetime.now().isoformat()})
        return {"status": "stopped", "message": "Bot durduruldu"}


@app.post("/api/reset")
async def reset_bot():
    """Reset the bot state and clear in-flight DB rows.

    Stops the bot, then:

    - Sets every open bet's status to 'cancelled' (audit row is
      preserved; exposure query filters on open_statuses so
      cancelled bets drop out of the dashboard totals).
    - Deletes all Analysis rows. They are regenerable on the next
      scan; keeping them would cause the 'total_signals' counter
      to remain non-zero after a reset.
    - Leaves WeatherMarket rows in place — they are the universe
      of tradable markets and are re-priced on the next scan.

    In-memory state is wiped last so the response uses fresh
    values. The reset is idempotent: pressing the button twice
    in a row is a no-op the second time.
    """
    # 1. Stop background loops first so they can't race the cleanup
    #    and re-insert rows we are about to delete.
    await stop_bot()

    # 2. DB cleanup. Use a single session so the changes are atomic.
    open_statuses = ("active", "open", "placed", "pending")
    cancelled_bets = 0
    deleted_analyses = 0
    db = get_db_session()
    try:
        cancelled_bets = (
            db.query(Bet)
            .filter(Bet.status.in_(open_statuses))
            .update({"status": "cancelled"}, synchronize_session=False)
        )
        deleted_analyses = (
            db.query(Analysis)
            .delete(synchronize_session=False)
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("reset_bot: DB cleanup failed: %s", exc)
        raise
    finally:
        db.close()

    # 3. In-memory state wipe. The /api/status handler now reads
    #    Bet/Analysis from the DB, so step 2 already dropped the
    #    counters to zero; these assignments are belt-and-braces.
    state.locked = False
    state.lock_reason = None
    state.total_signals = 0
    state.total_bets = 0
    state.last_scan = None

    logger.info(
        "reset_bot: cancelled %d open bets, deleted %d analyses",
        cancelled_bets,
        deleted_analyses,
    )

    return {
        "status": "reset",
        "message": "Bot sıfırlandı",
        "cancelled_bets": int(cancelled_bets or 0),
        "deleted_analyses": int(deleted_analyses or 0),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time updates WebSocket endpoint."""
    await websocket.accept()
    state.websocket_clients.append(websocket)

    await websocket.send_json(
        {
            "type": "connected",
            "is_running": state.is_running,
            "timestamp": datetime.now().isoformat(),
        }
    )

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in state.websocket_clients:
            state.websocket_clients.remove(websocket)


# Independent Background Scan & Bet Loop (uses decoupled Jobs sequentially)
async def scan_and_bet_loop():
    """Sequentially triggers fetch, parse, weather, analyze, and bet placement jobs.

    All blocking work is offloaded to a thread via `asyncio.to_thread` so
    the FastAPI event loop stays responsive. Without this, a single scan
    cycle that fetches 50+ Polymarket markets and runs 50+ weather/forecast
    calls can block the loop for 30+ seconds, which makes every
    `/api/status`, `/api/signals`, and the WebSocket push hang — and
    makes the user think "Start button doesn't work after Reset".
    """
    from database.models import Bet, Analysis
    from jobs.scheduler import (
        run_fetch_markets,
        run_parse_markets,
        run_fetch_weather,
        run_analyze,
        run_place_bets,
        run_update_prices,
    )

    def _run_cycle() -> int:
        """One scan cycle. Returns the number of bets placed.

        Runs in a worker thread via asyncio.to_thread, so any DB
        or HTTP work here cannot stall the FastAPI event loop.
        """
        run_fetch_markets()
        run_parse_markets()
        run_fetch_weather()
        run_analyze()
        n = run_place_bets()
        try:
            run_update_prices()
        except Exception as e:
            logger.warning("Price refresh failed: %s", e)
        return n

    def _refresh_counters() -> tuple:
        """Refresh total_bets/total_signals from the DB. Returns (bets, signals)."""
        with get_db_session() as session:
            bets = (
                session.query(Bet)
                .filter(Bet.status.in_(("active", "open", "placed", "pending")))
                .count()
            )
            signals = (
                session.query(Analysis)
                .filter(Analysis.should_bet.is_(True))
                .count()
            )
        return bets, signals

    while state.is_running:
        try:
            logger.info("Executing Scan & Bet job cycle...")
            n_placed = await asyncio.to_thread(_run_cycle)
            total_bets, total_signals = await asyncio.to_thread(_refresh_counters)
            state.total_bets = total_bets
            state.total_signals = total_signals
            state.last_scan = datetime.now()
            await broadcast_message(
                {
                    "type": "scan_complete",
                    "timestamp": state.last_scan.isoformat(),
                    "markets_scanned": 50,
                    "total_signals": state.total_signals,
                    "total_bets": state.total_bets,
                    "placed_this_cycle": n_placed,
                }
            )
        except Exception as e:
            logger.error("Scan loop cycle error: %s", e, exc_info=True)

        await asyncio.sleep(state.config.SCAN_INTERVAL)


# Independent Background Settlement Loop (uses decoupled jobs)
async def settlement_loop():
    """Sequentially triggers settlement checking. Blocking work runs in
    a worker thread to keep the FastAPI event loop responsive.
    """
    from jobs.scheduler import run_settle
    while state.is_running:
        try:
            logger.info("Executing Settlement job cycle...")
            await asyncio.to_thread(run_settle)
        except Exception as e:
            logger.error("Settlement loop cycle error: %s", e, exc_info=True)

        await asyncio.sleep(state.config.SETTLEMENT_INTERVAL)


def run_cli():
    """Entry point for executing command line instructions."""
    parser = argparse.ArgumentParser(description="Weather Betting Bot")
    parser.add_argument("command", choices=[
        "run",           # starts server & scheduler
        "fetch",         # runs once
        "parse",
        "weather",
        "analyze",
        "bet",
        "settle",
        "report",
        "test"
    ])
    args = parser.parse_args()

    # DB'yi hazırla
    init_db()
    logger.info("Database hazır")

    from jobs.scheduler import (
        run_fetch_markets, run_parse_markets, run_fetch_weather,
        run_analyze, run_place_bets, run_settle, run_report
    )

    commands = {
        "fetch": run_fetch_markets,
        "parse": run_parse_markets,
        "weather": run_fetch_weather,
        "analyze": run_analyze,
        "bet": run_place_bets,
        "settle": run_settle,
        "report": run_report,
    }

    if args.command == "run":
        import uvicorn
        logger.info("🚀 Bot başlatılıyor...")
        port = int(os.getenv("PORT", str(config.PORT)))
        uvicorn.run(app, host=config.HOST, port=port)
    elif args.command == "test":
        logger.info("🧪 Test modu...")
        for name, func in commands.items():
            if name != "bet" and name != "settle":
                try:
                    result = func()
                    logger.info(f"  {name}: {result}")
                except Exception as e:
                    logger.error(f"  {name}: HATA - {e}")
    else:
        result = commands[args.command]()
        print(result)


if __name__ == "__main__":
    run_cli()
