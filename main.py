"""FastAPI application for QwenBot — Polymarket weather betting bot.

Provides REST API endpoints for status, markets, signals, history, cleanup,
and WebSocket push. The bot runs fetch → parse → forecast → analyze →
place → settle cycles at configurable intervals.
"""

import argparse
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from config.logging_config import setup_logging

# Package Imports
from config.settings import config
from database.db import ensure_initial_portfolio, get_db_session, get_db_session_factory, init_db
from database.models import OPEN_BET_STATUSES, Analysis, Bet, Portfolio, WeatherMarket
from engine.calculator import WeatherEngine
from engine.strategy import BettingEngine, RiskManager, SIALoop
from executor.settler import SettlementEngine
from scrapers.polymarket import PolymarketScraper
from utils.price_sanity import safe_ev

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
        self.websocket_clients: list[WebSocket] = []
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
        self.sia_last_run = None  # datetime of last SIA optimization
        self.sia_interval_hours = 24  # run SIA once a day

    def initialize_modules(self):
        """Initialize all modular components."""
        self.db_session_factory = get_db_session_factory()
        self.data_fetcher = PolymarketScraper()
        self.weather_engine = WeatherEngine(self.db_session_factory, self.config)
        self.risk_manager = RiskManager(None, self.config)
        self.betting_engine = BettingEngine(
            None, self.risk_manager, self.weather_engine
        )
        self.settlement_engine = SettlementEngine()
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
        ensure_initial_portfolio()
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
    allow_origins=["http://localhost:8091", "http://127.0.0.1:8091"],
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
    return HTMLResponse("<h1>Dashboard yukleniyor...</h1>")


@app.get("/api/status")
async def get_status():
    """Get bot status and metrics with strict accounting."""
    from sqlalchemy import func

    from database.models import Analysis, Bet
    db = get_db_session()
    try:
        portfolio = db.query(Portfolio).filter(Portfolio.id == 1).first()

        # 1. Realized PnL (Closed bets)
        from datetime import datetime, timezone
        _ts = datetime.now(timezone.utc).replace(tzinfo=None)
        _today_start = _ts.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_pnl = (
            db.query(func.coalesce(func.sum(Bet.pnl), 0.0))
            .filter(Bet.status.in_(("won", "lost", "settled")), Bet.settled_at >= _today_start)
            .scalar()
        ) or 0.0

        realized_pnl_db = (
            db.query(func.coalesce(func.sum(Bet.pnl), 0.0))
            .filter(Bet.status.in_(("won", "lost", "settled")))
            .scalar()
        ) or 0.0

        # 2. Unrealized PnL (Open bets)
        open_statuses = OPEN_BET_STATUSES
        unrealized_pnl_db = (
            db.query(func.coalesce(func.sum(Bet.unrealized_pnl), 0.0))
            .filter(Bet.status.in_(open_statuses))
            .scalar()
        ) or 0.0

        # 3. Counts
        win_count = db.query(Bet).filter(Bet.status == "won").count()
        loss_count = db.query(Bet).filter(Bet.status == "lost").count()
        total_bets_db = db.query(Bet).filter(Bet.status.in_(open_statuses)).count()
        total_signals_db = db.query(Analysis).filter(Analysis.should_bet.is_(True)).count()

        exposure_db = (
            db.query(func.coalesce(func.sum(Bet.amount), 0.0))
            .filter(Bet.status.in_(open_statuses))
            .scalar()
        ) or 0.0

        initial_capital = state.config.INITIAL_PORTFOLIO
        total_pnl = realized_pnl_db + unrealized_pnl_db

        # Total amount staked in settled bets (sum of all bet amounts
        # regardless of win/loss). ROI = PnL / total_stake, NOT PnL / initial.
        total_stake_settled = (
            db.query(func.coalesce(func.sum(Bet.amount), 0.0))
            .filter(Bet.status.in_(("won", "lost", "settled")))
            .scalar()
        ) or 0.0

        # ROI: profit per dollar wagered (betting convention)
        total_roi = (total_pnl / total_stake_settled) * 100 if total_stake_settled > 0 else 0
        # Daily ROI: daily PnL / total stake settled today
        total_stake_today = (
            db.query(func.coalesce(func.sum(Bet.amount), 0.0))
            .filter(Bet.status.in_(("won", "lost", "settled")), Bet.settled_at >= _today_start)
            .scalar()
        ) or 0.0
        daily_roi = (daily_pnl / total_stake_today) * 100 if total_stake_today > 0 else 0

        return {
            "is_running": state.is_running,
            "locked": state.locked,
            "portfolio": {
                "initial": initial_capital,
                "current": initial_capital - exposure_db,  # net sermaye = bastaki - acik bet
                "daily_pnl": daily_pnl,
                "daily_roi": daily_roi,
                "unrealized_pnl": float(unrealized_pnl_db),
                "realized_pnl": float(realized_pnl_db),
                "total_pnl": total_pnl,
                "total_roi": total_roi,
                "exposure": float(exposure_db),
                "max_exposure": round((initial_capital + realized_pnl_db) * state.config.TOTAL_EXPOSURE_PCT, 2),
            },
            "stats": {
                "total_signals": total_signals_db,
                "total_bets": total_bets_db,
                "win_count": win_count,
                "loss_count": loss_count,
                "total_closed": win_count + loss_count,
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

@app.get("/api/markets")
async def get_markets():
    """Get all future active weather markets AND missed signals (rejected bets)."""
    from datetime import timedelta

    from database.models import Analysis, Bet, WeatherForecast, WeatherMarket
    from engine.calculator import Calculator
    db = get_db_session()
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # 1. Fetch missed signals (should_bet=True but no active bet)
        # These are the "164 - 8 = 156" signals
        missed_signals = (
            db.query(Analysis, WeatherMarket)
            .join(WeatherMarket, Analysis.market_id == WeatherMarket.id)
            .filter(Analysis.should_bet.is_(True))
            .filter(~Analysis.market_id.in_(
                db.query(Bet.market_id).filter(Bet.status.in_(["placed", "active", "open"]))
            ))
            .order_by(Analysis.analyzed_at.desc())
            .all()
        )

        market_list = []
        for analysis, m in missed_signals:
            market_list.append({
                "id": m.id,
                "city": m.city,
                "city_code": "SIGNAL",
                "date": m.target_date.isoformat() if m.target_date else None,
                "outcome_type": m.metric or "YES",
                "strike_temp": float(m.threshold) if m.threshold else 0,
                "current_yes_bid": float(m.yes_price) if m.yes_price else 0,
                "current_no_bid": float(m.no_price) if m.no_price else 0,
                "model_prob": float(analysis.estimated_probability),
                "edge": float(analysis.edge),
                "ev": safe_ev(analysis.estimated_probability, m.yes_price or 0.5),
                "status": "REJECTED (Risk Cap)"
            })

        # 2. Fetch other open markets (today + 7 days)
        upper = now + timedelta(days=7)
        markets = (
            db.query(WeatherMarket)
            .filter(
                WeatherMarket.target_date >= now,
                WeatherMarket.target_date <= upper,
                WeatherMarket.status == "open",
                ~WeatherMarket.id.in_([m["id"] for m in market_list])
            )
            .limit(100)
            .all()
        )

        calc = Calculator()
        for m in markets:
            if m.yes_price is None or m.threshold is None:
                continue
            current_price = float(m.yes_price)
            model_prob = current_price
            forecasts = (
                db.query(WeatherForecast)
                .filter(WeatherForecast.market_id == m.id)
                .order_by(WeatherForecast.fetched_at.desc())
                .limit(8)
                .all()
            )
            if forecasts:
                latest_vals = [f.predicted_value for f in forecasts]
                days_ahead = max((m.target_date - now).days, 1)
                model_prob = calc.estimate_probability(latest_vals, float(m.threshold), days_ahead)

            market_list.append({
                "id": m.id,
                "city": m.city,
                "city_code": "",
                "date": m.target_date.isoformat() if m.target_date else None,
                "outcome_type": m.metric or "YES",
                "strike_temp": float(m.threshold),
                "current_yes_bid": current_price,
                "current_no_bid": m.no_price or (1-current_price),
                "model_prob": model_prob,
                "edge": model_prob - current_price,
                "ev": safe_ev(model_prob, current_price),
                "status": "OPEN"
            })

        return {"markets": market_list, "count": len(market_list)}
    except Exception as e:
        logger.error("Markets API error: %s", e)
        return {"error": str(e), "markets": []}
    finally:
        db.close()

@app.get("/api/bets")
async def get_bets(status: str = "", limit: int = 100, offset: int = 0):
    """Get all bets with optional status filter and pagination.

    Query params:
      status  (str, optional)  -- comma-separated list of statuses to filter by.
                                Omitting returns ALL statuses.
      limit   (int, default 100)
      offset  (int, default 0)
    """
    db = get_db_session()
    try:
        q = db.query(Bet)
        if status:
            statuses = [s.strip() for s in status.split(",") if s.strip()]
            q = q.filter(Bet.status.in_(statuses))
        total = q.count()
        rows = q.order_by(Bet.placed_at.desc()).offset(offset).limit(limit).all()
        bets = []
        for b in rows:
            bets.append({
                "id": b.id,
                "market_id": b.market_id,
                "city": b.city or "",
                "side": b.side or b.outcome or "YES",
                "amount": float(b.amount or 0),
                "entry_price": float(b.entry_price or b.price or 0),
                "current_price": float(b.current_price or b.entry_price or b.price or 0),
                "status": b.status,
                "realized_pnl": float(b.realized_pnl or 0),
                "unrealized_pnl": float(b.unrealized_pnl or 0),
                "placed_at": b.placed_at.isoformat() if b.placed_at else None,
                "settled_at": b.settled_at.isoformat() if b.settled_at else None,
            })
        return {"bets": bets, "count": len(bets), "total": total}
    except Exception as e:
        logger.error("Bets API error: %s", e)
        return {"error": str(e), "bets": [], "count": 0, "total": 0}
    finally:
        db.close()

# Keep other endpoints (signals, history, cleanup, start, stop, reset, ws, loops, run_cli)
# exactly as they were in the previous successful read, but I'll write the full file
# to ensure no truncation.

def _safe_parse_ladder(raw):
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, list) else []
    except Exception:
        return []

@app.get("/api/signals")
async def get_signals():
    """Get all currently active (open) bets with live edge/price data."""
    db = get_db_session()
    try:
        active_bets = db.query(Bet).filter(Bet.status.in_(OPEN_BET_STATUSES)).all()
        signals = []
        for bet in active_bets:
            market = db.query(WeatherMarket).filter(WeatherMarket.id == bet.market_id).first()
            res_date = market.target_date if market else None
            entry = bet.entry_price if bet.entry_price is not None else bet.price
            current = bet.current_price if bet.current_price is not None else bet.entry_price
            fair_value = None
            live_edge = None
            entry_edge = None
            move_pct = None
            try:
                latest = (
                    db.query(Analysis)
                    .filter(Analysis.market_id == bet.market_id)
                    .order_by(Analysis.analyzed_at.desc())
                    .first()
                )
                if latest:
                    fair_value = float(latest.estimated_probability)
                    if current is not None:
                        live_edge = fair_value - current
                if bet.analysis_id:
                    origin = db.query(Analysis).filter(Analysis.id == bet.analysis_id).first()
                    if origin:
                        entry_edge = float(origin.edge)
                if entry and current and entry > 0:
                    move_pct = (current - entry) / entry
            except Exception:
                pass
            signals.append({
                "id": bet.id, "market_id": bet.market_id, "city": bet.city or (market.city if market else "Unknown"),
                "outcome": bet.side or bet.outcome or "YES", "entry_price": entry, "current_price": current,
                "stake_amount": bet.amount or bet.stake_amount, "unrealized_pnl": float(bet.unrealized_pnl or 0.0),
                "fair_value": fair_value, "edge": live_edge, "entry_edge": entry_edge, "live_edge": live_edge,
                "move_pct": move_pct, "ladder_orders": _safe_parse_ladder(bet.ladder_data),
                "placed_at": bet.placed_at.isoformat() if bet.placed_at else None,
                "resolution_date": res_date.isoformat() if res_date else None, "status": bet.status
            })
        return {"signals": signals, "count": len(signals)}
    finally:
        db.close()

@app.get("/api/history")
async def get_history():
    """Get settled bet history with win/loss stats."""
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
            history.append({
                "id": bet.id, "city": bet.city, "outcome": bet.side or "YES", "entry_price": bet.price,
                "stake_amount": bet.amount, "realized_pnl": bet.pnl or 0.0, "result": "WIN" if bet.pnl > 0 else "LOSS",
                "placed_at": bet.placed_at.isoformat() if bet.placed_at else None,
                "settled_at": bet.settled_at.isoformat() if bet.settled_at else None,
            })
        win_rate = (total_won / (total_won + total_lost) * 100) if (total_won + total_lost) > 0 else 0
        return {
            "history": history,
            "stats": {
                "total_won": total_won,
                "total_lost": total_lost,
                "win_rate": round(win_rate, 2),
            },
        }
    finally:
        db.close()

@app.post("/api/cleanup")
async def cleanup_old_data():
    """Cancel stale open bets and refund their stakes (ladder-aware)."""
    db = get_db_session()
    try:
        _ts = datetime.now(timezone.utc).replace(tzinfo=None)
        _today_start = _ts.replace(hour=0, minute=0, second=0, microsecond=0)
        stale_analyses = (
            db.query(Analysis)
            .filter(Analysis.should_bet.is_(True), Analysis.analyzed_at < _today_start)
            .delete(synchronize_session=False)
        )
        stale_bets = db.query(Bet).filter(Bet.status.in_(OPEN_BET_STATUSES), Bet.placed_at < _today_start).all()
        cancelled = 0
        for bet in stale_bets:
            bet.status = "cancelled"
            bet.settled_at = datetime.now(timezone.utc).replace(tzinfo=None)

            # Calculate the actual debited amount — for ladder bets only
            # filled rungs were debited; for flat bets the full amount.
            from utils.accounting import credit_sale
            ladder = _safe_parse_ladder(bet.ladder_data)
            if ladder:
                filled_amount = sum(
                    float(rung.get("amount", 0))
                    for rung in ladder
                    if rung.get("status") == "filled"
                )
                refund_amount = filled_amount if filled_amount > 0 else float(bet.amount or 0)
            else:
                refund_amount = float(bet.amount or 0)

            credit_sale(db, refund_amount, f"cleanup_refund:bet_{bet.id}")
            cancelled += 1
        db.commit()
        return {"deleted_analyses": stale_analyses, "cancelled_bets": cancelled}
    finally:
        db.close()

@app.post("/api/start")
async def start_bot():
    """Start the scan-and-bet and settlement background loops."""
    async with state.start_stop_lock:
        if state.is_running:
            return {"status": "already_running"}
        state.is_running = True
        state.locked = False
        state.tasks["scan_and_bet"] = asyncio.create_task(scan_and_bet_loop())
        state.tasks["settlement"] = asyncio.create_task(settlement_loop())
        return {"status": "started"}

@app.post("/api/stop")
async def stop_bot():
    """Stop all background loops and cancel pending tasks."""
    async with state.start_stop_lock:
        state.is_running = False
        for t in list(state.tasks.values()):
            if not t.done():
                t.cancel()
        state.tasks.clear()
        return {"status": "stopped"}

@app.post("/api/reset")
async def reset_bot():
    """Reset the bot state and clear in-flight DB rows WITHOUT auto-restart."""
    await stop_bot()
    db = get_db_session()
    try:
        # Clear all operational data
        db.query(Bet).delete()
        db.query(Analysis).delete()

        # Reset portfolio to exactly 1000
        pf = db.query(Portfolio).filter(Portfolio.id == 1).first()
        if not pf:
            pf = Portfolio(id=1)
            db.add(pf)

        pf.cash_balance = 1000.0
        pf.initial_value = 1000.0
        pf.current_value = 1000.0
        pf.total_value = 1000.0
        pf.total_realized_pnl = 0.0
        pf.daily_pnl = 0.0
        pf.total_won = 0
        pf.total_lost = 0

        db.commit()

        # Reset in-memory state
        state.total_signals = 0
        state.total_bets = 0
        state.last_scan = None

        return {
            "status": "reset",
            "message": "Sistem sifirlandi. Lutfen manuel olarak baslatin.",
            "portfolio": {
                "current": 1000.0,
                "exposure": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0
            }
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Reset error: {e}")
        return {"error": str(e)}
    finally:
        db.close()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    state.websocket_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in state.websocket_clients:
            state.websocket_clients.remove(websocket)

async def scan_and_bet_loop():
    """Background loop: fetch, parse, forecast, analyze, place bets, manage risk."""
    from jobs.scheduler import (
        run_analyze,
        run_fetch_markets,
        run_fetch_weather,
        run_parse_markets,
        run_place_bets,
        run_risk_management,
        run_update_prices,
    )
    while state.is_running:
        try:
            await asyncio.to_thread(run_fetch_markets)
            await asyncio.to_thread(run_parse_markets)
            await asyncio.to_thread(run_fetch_weather)
            await asyncio.to_thread(run_analyze)
            await asyncio.to_thread(run_place_bets)
            await asyncio.to_thread(run_update_prices)
            # Aktif risk yönetimi: stop-loss, take-profit, time-decay, trailing stop
            await asyncio.to_thread(run_risk_management)
        except Exception as e:
            logger.error("Scan error: %s", e)
        await asyncio.sleep(state.config.SCAN_INTERVAL)

async def settlement_loop():
    """Background loop: run SIA optimization and settle resolved bets."""
    from jobs.scheduler import run_settle
    while state.is_running:
        try:
            if state.sia_loop:
                await asyncio.to_thread(state.sia_loop.run_optimization_cycle)
            await asyncio.to_thread(run_settle)
        except Exception as e:
            logger.error("Settle error: %s", e)
        await asyncio.sleep(state.config.SETTLEMENT_INTERVAL)

def run_cli():
    """CLI entry point: run, reset, fetch, parse, weather, analyze, bet, settle, report."""
    parser = argparse.ArgumentParser()
    parser.add_argument("command")
    args = parser.parse_args()
    init_db()
    ensure_initial_portfolio()
    from jobs.scheduler import (
        run_analyze,
        run_fetch_markets,
        run_fetch_weather,
        run_parse_markets,
        run_place_bets,
        run_report,
        run_settle,
    )
    cmds = {
        "fetch": run_fetch_markets,
        "parse": run_parse_markets,
        "weather": run_fetch_weather,
        "analyze": run_analyze,
        "bet": run_place_bets,
        "settle": run_settle,
        "report": run_report,
    }
    if args.command == "run":
        import uvicorn  # noqa: I001
        uvicorn.run(app, host=config.HOST, port=config.PORT)
    elif args.command == "reset":
        db = get_db_session()
        db.query(Bet).update({"status": "cancelled"})
        db.query(Analysis).delete()
        pf = db.query(Portfolio).filter(Portfolio.id == 1).first()
        pf.cash_balance = 1000.0
        db.commit()
        db.close()
    elif args.command in cmds:
        print(cmds[args.command]())

if __name__ == "__main__":
    run_cli()
