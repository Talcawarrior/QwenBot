
import os
import json
import argparse
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

# Package Imports
from config.settings import config
from config.logging_config import setup_logging
from database.db import init_db, get_db_session, get_db_session_factory, ensure_initial_portfolio
from database.models import Portfolio, WeatherMarket, Bet, Analysis
from engine.strategy import RiskManager, BettingEngine, SIALoop
from engine.calculator import WeatherEngine
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
    from database.models import Bet, Analysis
    from sqlalchemy import func
    db = get_db_session()
    try:
        portfolio = db.query(Portfolio).filter(Portfolio.id == 1).first()
        
        # 1. Realized PnL (Closed bets)
        from datetime import datetime, timezone
        _today_start = datetime.now(timezone.utc).replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
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
        open_statuses = ("active", "open", "placed", "pending")
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
        
        # ROI
        total_roi = (total_pnl / initial_capital) * 100 if initial_capital > 0 else 0
        daily_roi = (daily_pnl / initial_capital) * 100 if initial_capital > 0 else 0

        return {
            "is_running": state.is_running,
            "locked": state.locked,
            "portfolio": {
                "initial": initial_capital,
                "current": float(portfolio.total_value) if portfolio else initial_capital,
                "daily_pnl": daily_pnl,
                "daily_roi": daily_roi,
                "unrealized_pnl": float(unrealized_pnl_db),
                "realized_pnl": float(realized_pnl_db),
                "total_pnl": total_pnl,
                "total_roi": total_roi,
                "exposure": float(exposure_db),
                "smart_pool": initial_capital * state.config.SMART_POOL_PCT,
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
    from engine.calculator import Calculator
    from database.models import WeatherForecast, Analysis, Bet, WeatherMarket
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
            if m.yes_price is None or m.threshold is None: continue
            current_price = float(m.yes_price)
            model_prob = current_price
            forecasts = db.query(WeatherForecast).filter(WeatherForecast.market_id == m.id).order_by(WeatherForecast.fetched_at.desc()).limit(8).all()
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

# Keep other endpoints (signals, history, cleanup, start, stop, reset, ws, loops, run_cli) 
# exactly as they were in the previous successful read, but I'll write the full file
# to ensure no truncation.

def _safe_parse_ladder(raw):
    if not raw: return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, list) else []
    except Exception: return []

@app.get("/api/signals")
async def get_signals():
    db = get_db_session()
    try:
        active_bets = db.query(Bet).filter(Bet.status.in_(["active", "open", "placed", "pending"])).all()
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
                latest = db.query(Analysis).filter(Analysis.market_id == bet.market_id).order_by(Analysis.analyzed_at.desc()).first()
                if latest:
                    fair_value = float(latest.estimated_probability)
                    if current is not None: live_edge = fair_value - current
                if bet.analysis_id:
                    origin = db.query(Analysis).filter(Analysis.id == bet.analysis_id).first()
                    if origin: entry_edge = float(origin.edge)
                if entry and current and entry > 0: move_pct = (current - entry) / entry
            except Exception: pass
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
    finally: db.close()

@app.get("/api/history")
async def get_history():
    db = get_db_session()
    try:
        settled_bets = db.query(Bet).filter(Bet.status.in_(["settled", "won", "lost"])).order_by(Bet.settled_at.desc()).limit(50).all()
        history = []
        total_won = 0
        total_lost = 0
        for bet in settled_bets:
            if bet.pnl > 0: total_won += 1
            else: total_lost += 1
            history.append({
                "id": bet.id, "city": bet.city, "outcome": bet.side or "YES", "entry_price": bet.price,
                "stake_amount": bet.amount, "realized_pnl": bet.pnl or 0.0, "result": "WIN" if bet.pnl > 0 else "LOSS",
                "settled_at": bet.settled_at.isoformat() if bet.settled_at else None
            })
        win_rate = (total_won / (total_won + total_lost) * 100) if (total_won + total_lost) > 0 else 0
        return {"history": history, "stats": {"total_won": total_won, "total_lost": total_lost, "win_rate": round(win_rate, 2)}}
    finally: db.close()

@app.post("/api/cleanup")
async def cleanup_old_data():
    db = get_db_session()
    try:
        _today_start = datetime.now(timezone.utc).replace(tzinfo=None).replace(hour=0, minute=0, second=0, microsecond=0)
        stale_analyses = db.query(Analysis).filter(Analysis.should_bet.is_(True), Analysis.analyzed_at < _today_start).delete(synchronize_session=False)
        stale_bets = db.query(Bet).filter(Bet.status.in_(("active", "open", "placed", "pending")), Bet.placed_at < _today_start).all()
        cancelled = 0
        for bet in stale_bets:
            bet.status = "cancelled"; bet.settled_at = datetime.now(timezone.utc).replace(tzinfo=None)
            portfolio = db.query(Portfolio).filter(Portfolio.id == 1).first()
            if portfolio: portfolio.cash_balance = (portfolio.cash_balance or 0.0) + float(bet.amount or 0.0)
            cancelled += 1
        db.commit()
        return {"deleted_analyses": stale_analyses, "cancelled_bets": cancelled}
    finally: db.close()

@app.post("/api/start")
async def start_bot():
    async with state.start_stop_lock:
        if state.is_running: return {"status": "already_running"}
        state.is_running = True; state.locked = False
        state.tasks["scan_and_bet"] = asyncio.create_task(scan_and_bet_loop())
        state.tasks["settlement"] = asyncio.create_task(settlement_loop())
        return {"status": "started"}

@app.post("/api/stop")
async def stop_bot():
    async with state.start_stop_lock:
        state.is_running = False
        for t in list(state.tasks.values()): 
            if not t.done(): t.cancel()
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
    await websocket.accept(); state.websocket_clients.append(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: 
        if websocket in state.websocket_clients: state.websocket_clients.remove(websocket)

async def scan_and_bet_loop():
    from jobs.scheduler import run_fetch_markets, run_parse_markets, run_fetch_weather, run_analyze, run_place_bets, run_update_prices
    while state.is_running:
        try:
            await asyncio.to_thread(run_fetch_markets); await asyncio.to_thread(run_parse_markets)
            await asyncio.to_thread(run_fetch_weather); await asyncio.to_thread(run_analyze)
            await asyncio.to_thread(run_place_bets); await asyncio.to_thread(run_update_prices)
        except Exception as e: logger.error("Scan error: %s", e)
        await asyncio.sleep(state.config.SCAN_INTERVAL)

async def settlement_loop():
    from jobs.scheduler import run_settle
    while state.is_running:
        try:
            if state.sia_loop: await asyncio.to_thread(state.sia_loop.run_optimization_cycle)
            await asyncio.to_thread(run_settle)
        except Exception as e: logger.error("Settle error: %s", e)
        await asyncio.sleep(state.config.SETTLEMENT_INTERVAL)

def run_cli():
    parser = argparse.ArgumentParser(); parser.add_argument("command")
    args = parser.parse_args(); init_db(); ensure_initial_portfolio()
    from jobs.scheduler import run_fetch_markets, run_parse_markets, run_fetch_weather, run_analyze, run_place_bets, run_settle, run_report
    cmds = {"fetch": run_fetch_markets, "parse": run_parse_markets, "weather": run_fetch_weather, "analyze": run_analyze, "bet": run_place_bets, "settle": run_settle, "report": run_report}
    if args.command == "run": import uvicorn; uvicorn.run(app, host=config.HOST, port=config.PORT)
    elif args.command == "reset":
        db = get_db_session()
        db.query(Bet).update({"status": "cancelled"}); db.query(Analysis).delete()
        pf = db.query(Portfolio).filter(Portfolio.id == 1).first()
        pf.cash_balance = 1000.0; db.commit(); db.close()
    elif args.command in cmds: print(cmds[args.command]())

if __name__ == "__main__": run_cli()
