"""ASIAbot Unified Server and CLI.

Extends QwenBot with the ASI-Evolve framework and high-fidelity 
prediction-market data ingestion.
"""

import argparse
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from config.logging_config import setup_logging
from config.settings import config, bot_config
from database.db import ensure_initial_portfolio, get_db_session, get_db_session_factory, init_db
from database.models import OPEN_BET_STATUSES, Analysis, Bet, Portfolio, WeatherMarket
from utils.price_sanity import safe_ev

# Import ASIAbot modules
from asi_engine.orchestrator import ASIAbotOrchestrator
from utils.weights_store import load_weights

setup_logging()
logger = logging.getLogger("ASIABOT_MAIN")


class ASIAbotState:
    """State manager for ASIAbot extending standard bot states."""

    def __init__(self):
        self.is_running = False
        self.locked = False
        self.last_scan = None
        self.websocket_clients: list[WebSocket] = []
        self.tasks = {}
        self.start_stop_lock = asyncio.Lock()
        
        # ASIAbot Orchestrator
        self.orchestrator = None

    def initialize(self):
        init_db()
        ensure_initial_portfolio()
        self.orchestrator = ASIAbotOrchestrator()
        logger.info("ASIAbot: Orchestrator and Cognition Base initialized successfully.")


state = ASIAbotState()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Lifespan context manager for ASIAbot startup and shutdown."""
    logger.info("ASIAbot starting...")
    state.initialize()
    yield
    # Shutdown
    logger.info("ASIAbot shutting down...")
    if state.tasks:
        for task in list(state.tasks.values()):
            if not task.done():
                task.cancel()
        state.tasks.clear()


app = FastAPI(title="⚡ ASIAbot - Self-Evolving Predictor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Serve the branded ASIAbot Dashboard"""
    dashboard_path = os.path.join(os.path.dirname(__file__), "asi_dashboard.html")
    if os.path.exists(dashboard_path):
        return FileResponse(dashboard_path)
    return HTMLResponse("<h1>ASIAbot Dashboard loading...</h1>")


@app.get("/api/status")
async def get_status():
    """Serve status including evolved strategy limits."""
    from sqlalchemy import func
    db = get_db_session()
    try:
        portfolio = db.query(Portfolio).filter(Portfolio.id == 1).first()
        
        # Calculate Realized & Unrealized PnL
        realized_pnl = (
            db.query(func.coalesce(func.sum(Bet.pnl), 0.0))
            .filter(Bet.status.in_(("won", "lost", "settled")))
            .scalar()
        ) or 0.0

        unrealized_pnl = (
            db.query(func.coalesce(func.sum(Bet.unrealized_pnl), 0.0))
            .filter(Bet.status.in_(OPEN_BET_STATUSES))
            .scalar()
        ) or 0.0

        win_count = db.query(Bet).filter(Bet.status == "won").count()
        loss_count = db.query(Bet).filter(Bet.status == "lost").count()
        total_bets = db.query(Bet).filter(Bet.status.in_(OPEN_BET_STATUSES)).count()
        total_signals = db.query(Analysis).filter(Analysis.should_bet.is_(True)).count()

        exposure = (
            db.query(func.coalesce(func.sum(Bet.amount), 0.0))
            .filter(Bet.status.in_(OPEN_BET_STATUSES))
            .scalar()
        ) or 0.0

        initial_capital = config.INITIAL_PORTFOLIO
        total_pnl = realized_pnl + unrealized_pnl
        
        # Calculate ROI
        total_stake_settled = (
            db.query(func.coalesce(func.sum(Bet.amount), 0.0))
            .filter(Bet.status.in_(("won", "lost", "settled")))
            .scalar()
        ) or 0.0
        total_roi = (total_pnl / total_stake_settled * 100) if total_stake_settled > 0 else 0.0

        return {
            "is_running": state.is_running,
            "locked": state.locked,
            "portfolio": {
                "initial": initial_capital,
                "current": initial_capital - exposure,
                "unrealized_pnl": float(unrealized_pnl),
                "realized_pnl": float(realized_pnl),
                "total_pnl": float(total_pnl),
                "total_roi": float(total_roi),
                "exposure": float(exposure),
                "max_exposure": round((initial_capital + realized_pnl) * config.TOTAL_EXPOSURE_PCT, 2),
            },
            "stats": {
                "total_signals": total_signals,
                "total_bets": total_bets,
                "win_count": win_count,
                "loss_count": loss_count,
                "total_closed": win_count + loss_count,
            },
            "limits": {
                "min_edge_pct": bot_config.strategy.min_edge * 100.0,
                "kelly_fraction_pct": bot_config.strategy.kelly_fraction * 100.0,
                "daily_stop_loss_pct": config.DAILY_LOSS_LIMIT * 100,
                "city_cap": config.CITY_CAP,
            },
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        db.close()


@app.get("/api/asi/weights")
async def get_asi_weights():
    """Retrieve current evolved weights."""
    weights = load_weights()
    if not weights:
        # Fallback to current memory weights
        weights = config.MODEL_WEIGHTS
    return weights


@app.get("/api/asi/cognition")
async def get_asi_cognition():
    """Retrieve ASI Cognition Base insights."""
    if not state.orchestrator:
        state.orchestrator = ASIAbotOrchestrator()
    return state.orchestrator.cognition_base.get_all_insights()


@app.post("/api/asi/evolve")
async def run_asi_evolve():
    """Run an autonomous evolution pipeline round (5 rounds)."""
    if not state.orchestrator:
        state.orchestrator = ASIAbotOrchestrator()
    
    # Run the evolution loop in an async executor to prevent blocking
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, state.orchestrator.run_evolution_pipeline, 5)
    return result


# Map standard QwenBot API endpoints for compatibility
@app.get("/api/markets")
async def get_markets():
    from main import get_markets as _gm
    return await _gm()


@app.get("/api/bets")
async def get_bets(status: str = "", limit: int = 100, offset: int = 0):
    from main import get_bets as _gb
    return await _gb(status, limit, offset)


@app.get("/api/signals")
async def get_signals():
    from main import get_signals as _gs
    return await _gs()


@app.get("/api/history")
async def get_history():
    from main import get_history as _gh
    return await _gh()


@app.post("/api/start")
async def start_bot():
    async with state.start_stop_lock:
        if state.is_running:
            return {"status": "already_running"}
        state.is_running = True
        
        # Start background tasks from main
        from main import scan_and_bet_loop, settlement_loop
        state.tasks["scan_and_bet"] = asyncio.create_task(scan_and_bet_loop())
        state.tasks["settlement"] = asyncio.create_task(settlement_loop())
        return {"status": "started"}


@app.post("/api/stop")
async def stop_bot():
    async with state.start_stop_lock:
        state.is_running = False
        for t in list(state.tasks.values()):
            if not t.done():
                t.cancel()
        state.tasks.clear()
        return {"status": "stopped"}


@app.post("/api/reset")
async def reset_bot():
    await stop_bot()
    from main import reset_bot as _rb
    return await _rb()


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


def run_cli():
    """CLI entry point for ASIAbot."""
    parser = argparse.ArgumentParser(description="ASIAbot CLI Interface")
    parser.add_argument("command", choices=["run", "evolve", "fetch", "weather", "analyze", "bet", "settle", "report", "reset"])
    args = parser.parse_args()

    init_db()
    ensure_initial_portfolio()

    if args.command == "run":
        logger.info("Starting ASIAbot FastAPI Server on port 8091...")
        uvicorn.run(app, host=config.HOST, port=config.PORT)
    elif args.command == "evolve":
        logger.info("Running ASIAbot Autonomous Evolution Loop on CLI...")
        orchestrator = ASIAbotOrchestrator()
        result = orchestrator.run_evolution_pipeline(5)
        print(f"\nEvolution successful! Best round: Round {result['round']}, Virtual ROI: {result['roi']:.2f}%")
    else:
        # Delegate standard operations to jobs/scheduler
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
            "weather": run_fetch_weather,
            "analyze": run_analyze,
            "bet": run_place_bets,
            "settle": run_settle,
            "report": run_report,
            "reset": lambda: "System reset completed. Run run/evolve next."
        }
        if args.command in cmds:
            print(cmds[args.command]())


if __name__ == "__main__":
    run_cli()
