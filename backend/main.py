"""
MAIN SERVER - FastAPI + WebSocket
- Backend API endpoints
- Real-time WebSocket updates
- HTML Dashboard serving
- Ladder Bet execution
- SIA Loop integration
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from betting_engine import BettingEngine
from config import Config
from data_fetcher import DataFetcher
from database import (
    Bet,
    Market,
    Portfolio,
    get_db_session,
    get_db_session_factory,
    init_db,
)
from risk_manager import RiskManager
from settlement import SettlementEngine
from sia_loop import SIALoop
from weather_engine import WeatherEngine


# Setup logging to file + console (critical fix)
def setup_logging():
    """Configure root logger with console and rotating file handlers."""
    log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "bot.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    # Guard against duplicate handlers on reload (BUG-16 fix)
    if any(
        isinstance(h, (logging.StreamHandler, RotatingFileHandler))
        for h in root_logger.handlers
    ):
        return

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(console_formatter)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(file_formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)


setup_logging()

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Lifespan context manager (replaces deprecated @on_event for FastAPI)"""
    # Startup
    logger.info("PolyMarket Ultimate Weather Bot starting...")
    init_db()
    state.initialize_modules()
    # Ensure initial portfolio row exists
    # (fixes missing portfolio.cash_balance / total_value crashes)
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
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.warning("Portfolio init warning: %s", e)
    logger.info("Database and all modules ready.")
    logger.info("POLYMARKET ULTIMATE HYBRID WEATHER BOT v4.0")
    logger.info(
        "Initial Portfolio: $%.2f | Smart Pool: %.1f%% | Kelly: %.1f%% | "
        "Daily Stop-Loss: %.1f%% | Max Bet: %.1f%% | City Cap: %d | "
        "SIA Loop: Active | Ladder Bets: Active | Dashboard: http://localhost:%s",
        state.config.INITIAL_PORTFOLIO,
        state.config.SMART_POOL_PCT * 100,
        state.config.KELLY_FRACTION * 100,
        state.config.DAILY_LOSS_LIMIT * 100,
        state.config.MAX_BET_PCT * 100,
        state.config.CITY_CAP,
        state.config.PORT,
    )
    yield
    # Shutdown
    logger.info("Bot shutting down...")
    if state.tasks:
        for task in list(state.tasks.values()):
            if not task.done():
                task.cancel()
        await asyncio.gather(*state.tasks.values(), return_exceptions=True)
        state.tasks.clear()
    # Close data fetcher session (BUG-20)
    if (
        hasattr(state, "data_fetcher")
        and state.data_fetcher
        and hasattr(state.data_fetcher, "close_session")
    ):
        try:
            asyncio.create_task(state.data_fetcher.close_session())
        except Exception:  # pylint: disable=broad-exception-caught
            pass


app = FastAPI(title="PolyMarket Ultimate Weather Bot", lifespan=lifespan)

# CORS - more restrictive for security (dev için localhost + same origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8091",
        "http://127.0.0.1:8091",
        "http://localhost:8090",
    ],
    allow_credentials=False,  # credentials=True ile * yasak, güvenlik için false
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# Global state
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
        self.tasks = {}  # BUG-06 fix: track background tasks for proper cancel
        self.start_stop_lock = asyncio.Lock()

        # Initialize modules
        self.config = Config()
        self.db_session_factory = None
        self.data_fetcher = None
        self.weather_engine = None
        self.risk_manager = None
        self.betting_engine = None
        self.settlement_engine = None
        self.sia_loop = None

    def initialize_modules(self):
        """Initialize all modules with db session factory (BUG 1 fix)."""
        self.db_session_factory = get_db_session_factory()
        self.data_fetcher = DataFetcher()
        self.weather_engine = WeatherEngine(self.db_session_factory, self.config)
        self.risk_manager = RiskManager(None, self.config)
        self.betting_engine = BettingEngine(
            None, self.risk_manager, self.weather_engine
        )
        self.settlement_engine = SettlementEngine(None, self.config)
        self.sia_loop = SIALoop(self.db_session_factory, self.config)


state = BotState()


# WebSocket Manager
async def broadcast_message(message: dict):
    """Broadcast message to all connected clients."""
    if not state.websocket_clients:
        return
    disconnected = []
    for client in state.websocket_clients:
        try:
            await client.send_json(message)
        except Exception:  # pylint: disable=broad-exception-caught
            disconnected.append(client)
    for client in disconnected:
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
    """Get bot status"""
    db = get_db_session()
    try:
        portfolio = db.query(Portfolio).filter(Portfolio.id == 1).first()
        daily_pnl = (
            state.risk_manager.get_daily_pnl()
            if state.risk_manager
            else 0.0
        )
        exposure = (
            state.risk_manager.get_total_exposure()
            if state.risk_manager
            else 0.0
        )

        return {
            "is_running": state.is_running,
            "locked": state.locked,
            "lock_reason": state.lock_reason,
            "portfolio": {
                "initial": state.config.INITIAL_PORTFOLIO,
                "current": portfolio.total_value
                if portfolio
                else state.config.INITIAL_PORTFOLIO,
                "daily_pnl": daily_pnl,
                "exposure": exposure,
                "smart_pool": state.config.INITIAL_PORTFOLIO
                * state.config.SMART_POOL_PCT,
            },
            "stats": {
                "total_signals": state.total_signals,
                "total_bets": state.total_bets,
                "last_scan": state.last_scan.isoformat() if state.last_scan else None,
            },
            "limits": {
                "max_bet_pct": state.config.MAX_BET_PCT * 100,
                "max_exposure_pct": state.config.TOTAL_EXPOSURE_PCT * 100,
                "daily_stop_loss_pct": state.config.DAILY_LOSS_LIMIT * 100,
                "city_cap": state.config.CITY_CAP,
            },
        }
    except Exception as e:  # pylint: disable=broad-exception-caught
        return {"error": str(e)}
    finally:
        db.close()


@app.get("/api/signals")
async def get_signals():
    """Get active signals and bets with Ladder details"""
    db = get_db_session()
    try:
        # Get active bets - BUG 5: use string values only (DB column is String, not Enum)
        active_bets = db.query(Bet).filter(Bet.status.in_(["active", "open"])).all()

        signals = []
        for bet in active_bets:
            # Fetch corresponding market to get the resolution date (closing date)
            market = db.query(Market).filter(Market.market_id == bet.market_id).first()
            res_date = market.resolution_date if market else None

            signals.append(
                {
                    "id": bet.id,
                    "market_id": bet.market_id,
                    "city": bet.city,
                    "outcome": bet.outcome if bet.outcome else "UNKNOWN",
                    "entry_price": bet.entry_price,
                    "current_price": bet.current_price or bet.entry_price,
                    "stake_amount": bet.stake_amount,
                    "unrealized_pnl": bet.unrealized_pnl or 0.0,
                    "fair_value": bet.fair_value,
                    "edge": bet.expected_value,
                    "ladder_orders": json.loads(bet.ladder_data)
                    if isinstance(bet.ladder_data, str) and bet.ladder_data
                    else (bet.ladder_data or []),
                    "placed_at": bet.placed_at.isoformat() if bet.placed_at else None,
                    "resolution_date": res_date.isoformat() if res_date else None,
                    "status": bet.status if bet.status else "UNKNOWN",
                }
            )

        return {"signals": signals, "count": len(signals)}
    except Exception as e:  # pylint: disable=broad-exception-caught
        return {"error": str(e), "signals": []}
    finally:
        db.close()


@app.get("/api/markets")
# pylint: disable=too-many-nested-blocks
async def get_markets():
    """Get all markets (Global Market Watch)"""
    db = get_db_session()
    try:
        # Filter out past/expired markets where resolution_date is in the past
        now = datetime.utcnow()
        markets = (
            db.query(Market)
            .filter(
                (Market.resolution_date >= now) | (Market.resolution_date.is_(None)),
                Market.status == "active"
            )
            .limit(100)
            .all()
        )
        market_list = []

        for m in markets:
            # Weather forecast - pass 4 args + compute prob
            # from strike (fixes TypeError and missing probability)
            forecast = None
            if (
                m.city_code
                and getattr(m, "latitude", None)
                and getattr(m, "longitude", None)
            ):
                try:
                    forecast = await state.weather_engine.get_multi_model_forecast(
                        m.city_code,
                        m.latitude,
                        m.longitude,
                        getattr(m, "resolution_date", None),
                    )
                except Exception as e:  # pylint: disable=broad-exception-caught
                    logger.error("get_markets forecast error: %s", e)

            if forecast:
                strike = getattr(m, "strike_temp", 25.0) or 25.0
                mtype = (
                    getattr(m, "range_type", "")
                    or getattr(m, "threshold_type", "above")
                    or ""
                )
                q = getattr(m, "question", "") or ""
                if "LOW" in str(mtype).upper() or "below" in q.lower():
                    model_prob = (
                        state.weather_engine.calculate_probability_below(
                            strike, forecast
                        )
                        if hasattr(state.weather_engine, "calculate_probability_below")
                        else 0.5
                    )
                else:
                    model_prob = (
                        state.weather_engine.calculate_probability_above(
                            strike, forecast
                        )
                        if hasattr(state.weather_engine, "calculate_probability_above")
                        else 0.5
                    )
            else:
                model_prob = 0.5

            current_price = (
                getattr(m, "current_yes_bid", None)
                or getattr(m, "yes_price", 0.5)
                or 0.5
            )
            edge = model_prob - current_price

            market_list.append(
                {
                    "id": m.id,
                    "city": getattr(m, "city", m.city_code or "Unknown"),
                    "city_code": m.city_code,
                    "date": m.resolution_date.isoformat()
                    if m.resolution_date
                    else None,
                    "outcome_type": m.outcome_type,
                    "strike_temp": m.strike_temp,
                    "current_yes_bid": current_price,
                    "current_no_bid": getattr(m, "current_no_bid", None)
                    or (1 - current_price),
                    "model_prob": model_prob,
                    "edge": edge,
                    "ev": (model_prob * (1 / current_price - 1)) - (1 - model_prob)
                    if current_price > 0
                    else 0,
                    "volume": m.volume or 0,
                }
            )

        return {"markets": market_list, "count": len(market_list)}
    except Exception as e:  # pylint: disable=broad-exception-caught
        return {"error": str(e), "markets": []}
    finally:
        db.close()


@app.get("/api/history")
async def get_history():
    """Get bet history (Kazanan/Kaybeden bahisler)"""
    db = get_db_session()
    try:
        # BUG 5: use string values only
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
            if bet.realized_pnl > 0:
                total_won += 1
            else:
                total_lost += 1

            history.append(
                {
                    "id": bet.id,
                    "city": bet.city,
                    "outcome": bet.outcome if bet.outcome else "UNKNOWN",
                    "entry_price": bet.entry_price,
                    "stake_amount": bet.stake_amount,
                    "realized_pnl": bet.realized_pnl or 0.0,
                    "result": "WIN" if bet.realized_pnl > 0 else "LOSS",
                    "settled_at": bet.settled_at.isoformat()
                    if bet.settled_at
                    else None,
                }
            )

        win_rate = (
            (total_won / (total_won + total_lost) * 100)
            if (total_won + total_lost) > 0
            else 0
        )

        return {
            "history": history,
            "stats": {
                "total_won": total_won,
                "total_lost": total_lost,
                "win_rate": round(win_rate, 2),
            },
        }
    except Exception as e:  # pylint: disable=broad-exception-caught
        return {"error": str(e), "history": []}
    finally:
        db.close()


@app.post("/api/start")
async def start_bot():
    """Start the bot"""
    async with state.start_stop_lock:
        if state.is_running:
            return {"status": "already_running"}

        state.is_running = True
        state.locked = False
        state.lock_reason = None

        # Start background tasks with names for tracking (BUG-06)
        state.tasks["scan"] = asyncio.create_task(scan_loop(), name="scan_loop")
        state.tasks["settlement"] = asyncio.create_task(
            settlement_loop(), name="settlement_loop"
        )
        state.tasks["sia"] = asyncio.create_task(
            sia_loop_scheduler(), name="sia_loop_scheduler"
        )

        await broadcast_message(
            {"type": "bot_started", "timestamp": datetime.now().isoformat()}
        )

        return {"status": "started", "message": "Bot başlatıldı"}


@app.post("/api/stop")
async def stop_bot():
    """Stop the bot"""
    async with state.start_stop_lock:
        state.is_running = False
        # Cancel tracked tasks (BUG-06)
        for task in list(state.tasks.values()):
            if not task.done():
                task.cancel()
        if state.tasks:
            await asyncio.gather(*state.tasks.values(), return_exceptions=True)
        state.tasks.clear()
        await broadcast_message(
            {"type": "bot_stopped", "timestamp": datetime.now().isoformat()}
        )
        return {"status": "stopped", "message": "Bot durduruldu"}


@app.post("/api/reset")
async def reset_bot():
    """Reset bot state"""
    # First stop tasks properly (BUG-17)
    await stop_bot()
    state.locked = False
    state.lock_reason = None
    state.total_signals = 0
    state.total_bets = 0
    state.last_scan = None
    return {"status": "reset", "message": "Bot sıfırlandı"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await websocket.accept()
    state.websocket_clients.append(websocket)

    # Send initial state
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
        try:
            state.websocket_clients.remove(websocket)
        except ValueError:
            pass


# Background Tasks
# pylint: disable=too-many-locals,too-many-branches,too-many-statements,too-many-nested-blocks
async def scan_loop():
    """Main scanning loop - Polymarket tarama ve sinyal analizi"""
    while state.is_running:
        try:
            logger.info("[%s] Scanning...", datetime.now().strftime("%H:%M:%S"))

            # BUG 1: Create fresh session per iteration
            if not state.db_session_factory:
                await asyncio.sleep(state.config.SCAN_INTERVAL)
                continue
            db = state.db_session_factory()
            try:
                # 1. Fetch Polymarket markets
                markets_data = await state.data_fetcher.fetch_polymarket_events()

                if not markets_data:
                    await asyncio.sleep(state.config.SCAN_INTERVAL)
                    continue

                # Markets'i veritabanına kaydet/güncelle (Upsert logic)
                for m in markets_data[:50]:  # İlk 50 market
                    try:
                        existing = (
                            db.query(Market)
                            .filter(
                                Market.market_id == m.get("market_id", m.get("id", ""))
                            )
                            .first()
                        )

                        if existing:
                            # Güncelle
                            existing.yes_price = m.get("yes_price", 0.5)
                            existing.no_price = m.get("no_price", 0.5)
                            existing.current_yes_bid = m.get("current_yes_bid", 0.5)
                            existing.current_no_bid = m.get("current_no_bid", 0.5)
                            existing.volume = m.get("volume", 0.0)
                            existing.status = "active"
                        else:
                            # Yeni kaydet
                            res_date = m.get("resolution_date")
                            if isinstance(res_date, str):
                                try:
                                    res_date = datetime.fromisoformat(
                                        res_date.replace("Z", "+00:00")
                                    )
                                except Exception:  # pylint: disable=broad-exception-caught
                                    res_date = None
                            new_market = Market(
                                market_id=(m.get("market_id") or m.get("id") or ""),
                                event_id=m.get("event_id", m.get("id", "")),
                                city=m.get("city", "Unknown"),
                                city_code=m.get("city_code", ""),
                                outcome_type=m.get("outcome_type", "YES"),
                                strike_temp=m.get("strike_temp", 80),
                                date=res_date,
                                resolution_date=res_date,
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
                    except Exception as e:  # pylint: disable=broad-exception-caught
                        logger.error(
                            "Market save error (%s): %s",
                            m.get("city", "Unknown"),
                            e,
                        )
                        db.rollback()

                portfolio_value = state.risk_manager.get_portfolio_value()

                # 2. Her market için analiz yap
                for market_data in markets_data[:10]:
                    # Fetch forecast using coords from data_fetcher
                    city_code = market_data.get("city_code", "")
                    coords = (
                        state.data_fetcher.get_city_coords(city_code)
                        if hasattr(state.data_fetcher, "get_city_coords")
                        else None
                    )
                    lat = coords[0] if coords else 0.0
                    lon = coords[1] if coords else 0.0
                    target_date = market_data.get("resolution_date")
                    forecast = None
                    if city_code and lat and lon:
                        try:
                            forecast = (
                                await state.weather_engine.get_multi_model_forecast(
                                    city_code, lat, lon, target_date
                                )
                            )
                        except Exception as e:  # pylint: disable=broad-exception-caught
                            logger.error("Forecast error for %s: %s", city_code, e)

                    # Market objesi oluştur (use Market directly)
                    market = Market(
                        market_id=market_data.get("market_id", ""),
                        event_id=market_data.get("event_id", market_data.get("id", "")),
                        city=market_data.get("city", "Unknown"),
                        city_code=city_code,
                        outcome_type=market_data.get("outcome_type", "YES"),
                        strike_temp=market_data.get("strike_temp", 80),
                        date=(
                            target_date if isinstance(target_date, datetime) else None
                        ),
                        resolution_date=(
                            target_date if isinstance(target_date, datetime) else None
                        ),
                        current_yes_bid=market_data.get(
                            "current_yes_bid",
                            market_data.get("yes_price", 0.5),
                        ),
                        current_no_bid=market_data.get(
                            "current_no_bid",
                            market_data.get("no_price", 0.5),
                        ),
                        latitude=lat,
                        longitude=lon,
                    )

                    # Analiz et (now passes forecast)
                    signal = await state.betting_engine.analyze_market(
                        market, portfolio_value, forecast
                    )

                    if signal:
                        cc = getattr(signal, "city_code", "") or market_data.get(
                            "city_code", ""
                        )
                        if not state.risk_manager.check_city_cap(cc):
                            continue
                        state.total_signals += 1

                        # Ladder bilgisi varsa logla
                        if signal.ladder_orders:
                            logger.info("LADDER: %d levels", len(signal.ladder_orders))

                        # Create a fresh session for the bet insert
                        bet_db = state.db_session_factory()
                        prev_db = state.betting_engine.db
                        try:
                            state.betting_engine.db = bet_db
                            bet = await state.betting_engine.execute_signal(
                                signal, market
                            )
                            if bet:
                                state.total_bets += 1
                                await broadcast_message(
                                    {
                                        "type": "new_bet",
                                        "data": {
                                            "id": bet.id,
                                            "city": bet.city,
                                            "outcome": getattr(bet, "outcome", "YES"),
                                            "stake": getattr(bet, "stake_amount", 0),
                                            "edge": getattr(signal, "edge", 0),
                                            "ladder": bool(
                                                getattr(signal, "ladder_orders", [])
                                            ),
                                        },
                                    }
                                )
                        finally:
                            state.betting_engine.db = prev_db
                            bet_db.close()

                state.last_scan = datetime.now()

                # Broadcast update
                await broadcast_message(
                    {
                        "type": "scan_complete",
                        "timestamp": state.last_scan.isoformat(),
                        "markets_scanned": len(markets_data),
                        "total_signals": state.total_signals,
                        "total_bets": state.total_bets,
                    }
                )
            finally:
                db.close()

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Scan error: %s", e)

        await asyncio.sleep(state.config.SCAN_INTERVAL)


# pylint: disable=too-many-nested-blocks
async def settlement_loop():
    """Settlement kontrol döngüsü - Her 1 dakikada bir"""
    while state.is_running:
        try:
            # BUG 1: Create fresh session per iteration for settlement
            if not state.db_session_factory:
                await asyncio.sleep(state.config.SETTLEMENT_INTERVAL)
                continue
            db = state.db_session_factory()
            prev_db = state.settlement_engine.db
            try:
                state.settlement_engine.db = db
                settled_count = await state.settlement_engine.settle_bets()
                # Risk manager daily_pnl ve circuit breaker sync
                if hasattr(state, "risk_manager") and state.risk_manager:
                    p = db.query(Portfolio).filter(Portfolio.id == 1).first()
                    if p:
                        state.risk_manager.daily_pnl = p.daily_pnl or 0.0
                        if state.risk_manager.is_bot_locked():
                            state.locked = True
                            state.lock_reason = "Daily stop-loss triggered"
                if settled_count > 0:
                    await broadcast_message(
                        {
                            "type": "settlement",
                            "count": settled_count,
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

                # Unrealized PnL güncelle
                await state.settlement_engine.update_market_prices()
            finally:
                state.settlement_engine.db = prev_db
                db.close()

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Settlement error: %s", e)

        await asyncio.sleep(state.config.SETTLEMENT_INTERVAL)


async def sia_loop_scheduler():
    """SIA Loop - Her 24 saatte bir optimizasyon"""
    while state.is_running:
        try:
            # Her 24 saatte bir çalıştır
            await asyncio.sleep(state.config.SIA_INTERVAL)

            if state.is_running:
                result = state.sia_loop.run_optimization_cycle()
                if result:
                    # Propagate SIA weights to WeatherEngine (HATA 5 fix)
                    if hasattr(state, "weather_engine") and state.weather_engine:
                        state.weather_engine.update_model_weights(
                            state.sia_loop.model_weights
                        )
                    await broadcast_message(
                        {
                            "type": "sia_optimized",
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("SIA Loop error: %s", e)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", str(Config.PORT)))
    uvicorn.run(app, host=Config.HOST, port=port)
