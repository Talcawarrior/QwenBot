"""
PolyMarkets Super Ladder Bot - Main Application
FastAPI + WebSocket Server for Paper Trading
"""
import asyncio
import logging
import json
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from config import config
from database import Database
from weather_engine import weather_engine
from ladder_engine import ladder_engine
from betting_engine import betting_engine
from polymarket_client import polymarket_client
from risk_manager import create_risk_manager
from settlement import create_settlement_engine

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_PATH),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="PolyMarkets Super Ladder Bot",
    description="Paper Trading Edition - Daily Temperature Markets",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
db: Optional[Database] = None
risk_manager = None
settlement_engine = None
websocket_clients: List[WebSocket] = []


# ============================================================================
# STARTUP / SHUTDOWN EVENTS
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Application startup"""
    global db, risk_manager, settlement_engine
    
    logger.info("Starting PolyMarkets Super Ladder Bot...")
    
    # Initialize database
    db = Database(config.DATABASE_PATH)
    logger.info(f"Database initialized: {config.DATABASE_PATH}")
    
    # Initialize managers
    risk_manager = create_risk_manager(db)
    settlement_engine = create_settlement_engine(db)
    
    # Start external services
    await weather_engine.start()
    await polymarket_client.start()
    
    # Start background tasks
    asyncio.create_task(scan_loop())
    asyncio.create_task(settlement_loop())
    asyncio.create_task(websocket_broadcast_loop())
    
    logger.info("Bot started successfully - PAPER MODE ACTIVE")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown"""
    logger.info("Shutting down bot...")
    
    await weather_engine.stop()
    await polymarket_client.stop()
    
    logger.info("Bot stopped")


# ============================================================================
# BACKGROUND TASKS
# ============================================================================

async def scan_loop():
    """Market scanning loop - runs every SCAN_INTERVAL seconds"""
    while True:
        try:
            logger.info(f"Scanning markets (interval: {config.SCAN_INTERVAL}s)...")
            
            # Risk check - daily reset
            risk_manager.auto_reset_daily()
            
            # Get portfolio state
            portfolio = db.get_portfolio()
            
            # Check if bot is stopped
            if risk_manager.is_stopped:
                logger.warning(f"Bot stopped: {risk_manager.stop_reason}")
                await asyncio.sleep(config.SCAN_INTERVAL)
                continue
            
            # Scan Polymarket markets
            markets = await polymarket_client.scan_markets()
            logger.info(f"Found {len(markets)} active markets")
            
            signals_generated = 0
            
            for market in markets:
                # Get city info
                city_info = config.get_city_by_name(market['city'])
                if not city_info:
                    continue
                
                # Determine side and price
                # For "High Temperature Above X°F" - YES means temp will be above X
                side = "YES" if market['market_type'] == 'high' else "NO"
                market_price = market.get('yes_price', 0.5) if side == "YES" else market.get('no_price', 0.5)
                
                # Get weather probability
                target_date = market.get('end_date', datetime.now().strftime('%Y-%m-%d'))
                
                prob_result = await weather_engine.get_temperature_probability(
                    lat=city_info['lat'],
                    lon=city_info['lon'],
                    strike_temp=market['strike_temp'],
                    side=side,
                    target_date=target_date
                )
                
                model_prob = prob_result.get('probability', 0.5)
                
                # Analyze signal
                signal = betting_engine.analyze_signal(
                    model_probability=model_prob,
                    market_price=market_price,
                    portfolio_capital=portfolio['current_capital'],
                    current_exposure=db.get_open_exposure(),
                    city_bets_count=db.get_open_bets_count(market['city']),
                    region_exposure=db.get_region_exposure(city_info.get('region', 'Unknown'))
                )
                
                # Log signal
                db.log_signal({
                    'condition_id': market['condition_id'],
                    'city': market['city'],
                    'market_type': market['market_type'],
                    'model_probability': model_prob,
                    'market_price': market_price,
                    'edge': signal['edge'],
                    'ev': signal['ev'],
                    'recommended_size': signal['recommended_size'],
                    'action': 'OPEN' if signal['should_bet'] else 'SKIP',
                    'reason': signal['reject_reason']
                })
                
                # Open bet if signal is good
                if signal['should_bet']:
                    permission = risk_manager.can_place_bet(
                        city=market['city'],
                        size=signal['recommended_size'],
                        portfolio=portfolio
                    )
                    
                    if permission['allowed']:
                        # Calculate ladder
                        ladder = ladder_engine.calculate_order_ladder(
                            total_size=signal['recommended_size'],
                            target_price=market_price,
                            side="BUY"
                        )
                        
                        # Create bet record
                        bet_data = {
                            'condition_id': market['condition_id'],
                            'event_id': market['event_id'],
                            'city': market['city'],
                            'region': city_info.get('region', 'Unknown'),
                            'market_type': market['market_type'],
                            'strike_temp': market['strike_temp'],
                            'side': side,
                            'entry_price': market_price,  # Will be updated on fill
                            'size': signal['recommended_size'],
                            'model_probability': model_prob,
                            'edge': signal['edge'],
                            'ev': signal['ev'],
                            'ladder_status': 'pending'
                        }
                        
                        bet_id = db.add_open_bet(bet_data)
                        
                        # Add ladder orders
                        for order in ladder:
                            db.add_ladder_order(
                                bet_id=bet_id,
                                condition_id=market['condition_id'],
                                level=order['level'],
                                price=order['price'],
                                size=order['size']
                            )
                        
                        signals_generated += 1
                        logger.info(
                            f"NEW BET: {market['city']} {market['market_type']} {market['strike_temp']}°F "
                            f"{side} @ ${signal['recommended_size']:.2f} (edge: {signal['edge']:.2%})"
                        )
            
            logger.info(f"Scan complete - {signals_generated} new bets opened")
            
            # Broadcast update to WebSocket clients
            await broadcast_portfolio_update()
            
        except Exception as e:
            logger.error(f"Scan loop error: {e}", exc_info=True)
        
        await asyncio.sleep(config.SCAN_INTERVAL)


async def settlement_loop():
    """Settlement check loop - runs every 60 seconds"""
    while True:
        try:
            result = await settlement_engine.check_settlements()
            
            if result['settled'] > 0:
                logger.info(f"Settled {result['settled']} bets")
                await broadcast_portfolio_update()
            
        except Exception as e:
            logger.error(f"Settlement loop error: {e}", exc_info=True)
        
        await asyncio.sleep(60)


async def websocket_broadcast_loop():
    """Broadcast portfolio updates to WebSocket clients every 5 seconds"""
    while True:
        try:
            await asyncio.sleep(5)
            await broadcast_portfolio_update()
        except Exception as e:
            logger.error(f"WebSocket broadcast error: {e}")


async def broadcast_portfolio_update():
    """Broadcast portfolio state to all connected WebSocket clients"""
    if not websocket_clients:
        return
    
    try:
        portfolio = db.get_portfolio()
        stats = db.get_stats()
        risk_summary = risk_manager.get_risk_summary(portfolio)
        
        message = {
            "type": "portfolio_update",
            "data": {
                "current_capital": portfolio['current_capital'],
                "total_pnl": portfolio['total_pnl'],
                "daily_pnl": portfolio['daily_pnl'],
                "total_bets": portfolio['total_bets'],
                "winning_bets": portfolio['winning_bets'],
                "losing_bets": portfolio['losing_bets'],
                "open_bets": stats['open_bets'],
                "win_rate": stats['win_rate'],
                "exposure_pct": stats['exposure_pct'],
                "risk_status": risk_summary['status'],
                "is_stopped": risk_summary['is_stopped'],
                "timestamp": datetime.now().isoformat()
            }
        }
        
        disconnected = []
        for client in websocket_clients:
            try:
                await client.send_json(message)
            except Exception:
                disconnected.append(client)
        
        # Remove disconnected clients
        for client in disconnected:
            websocket_clients.remove(client)
    
    except Exception as e:
        logger.error(f"Broadcast error: {e}")


# ============================================================================
# WEBSOCKET ENDPOINT
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket connection for real-time updates"""
    await websocket.accept()
    websocket_clients.append(websocket)
    
    logger.info(f"WebSocket client connected. Total clients: {len(websocket_clients)}")
    
    # Send initial data
    try:
        portfolio = db.get_portfolio()
        stats = db.get_stats()
        
        await websocket.send_json({
            "type": "initial_data",
            "data": {
                "portfolio": portfolio,
                "stats": stats,
                "paper_mode": config.is_paper_mode,
                "starting_capital": config.STARTING_CAPITAL
            }
        })
    except Exception as e:
        logger.error(f"Initial data send error: {e}")
    
    try:
        while True:
            # Keep connection alive, receive messages from client
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                msg_type = message.get('type')
                
                if msg_type == 'get_signals':
                    # Return recent signals
                    signals = db.get_recent_signals(limit=50)
                    await websocket.send_json({
                        "type": "signals_list",
                        "data": signals
                    })
                
                elif msg_type == 'get_open_bets':
                    # Return open bets with ladder status
                    open_bets = db.get_all_open_bets()
                    bets_with_ladders = []
                    
                    for bet in open_bets:
                        ladder_orders = db.get_ladder_orders(bet['condition_id'])
                        ladder_summary = ladder_engine.get_ladder_summary(ladder_orders)
                        
                        bets_with_ladders.append({
                            **bet,
                            'ladder': ladder_summary
                        })
                    
                    await websocket.send_json({
                        "type": "open_bets",
                        "data": bets_with_ladders
                    })
                
                elif msg_type == 'get_closed_bets':
                    # Return closed bets
                    closed = db.get_closed_bets(limit=100)
                    await websocket.send_json({
                        "type": "closed_bets",
                        "data": closed
                    })
                
                elif msg_type == 'get_risk_status':
                    # Return risk summary
                    portfolio = db.get_portfolio()
                    risk_summary = risk_manager.get_risk_summary(portfolio)
                    await websocket.send_json({
                        "type": "risk_status",
                        "data": risk_summary
                    })
                
                elif msg_type == 'reset_circuit_breaker':
                    # Reset circuit breaker (admin action)
                    risk_manager.reset_circuit_breaker()
                    await websocket.send_json({
                        "type": "circuit_breaker_reset",
                        "data": {"status": "ok"}
                    })
                
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from client: {data}")
    
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    finally:
        if websocket in websocket_clients:
            websocket_clients.remove(websocket)
        logger.info(f"WebSocket client removed. Total clients: {len(websocket_clients)}")


# ============================================================================
# REST API ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "PolyMarkets Super Ladder Bot",
        "version": "1.0.0",
        "mode": "PAPER TRADING",
        "status": "running"
    }


@app.get("/api/portfolio")
async def get_portfolio():
    """Get current portfolio state"""
    portfolio = db.get_portfolio()
    stats = db.get_stats()
    return {**portfolio, **stats}


@app.get("/api/open-bets")
async def get_open_bets():
    """Get all open bets with ladder status"""
    open_bets = db.get_all_open_bets()
    
    result = []
    for bet in open_bets:
        ladder_orders = db.get_ladder_orders(bet['condition_id'])
        ladder_summary = ladder_engine.get_ladder_summary(ladder_orders)
        
        result.append({
            **bet,
            'ladder': ladder_summary
        })
    
    return result


@app.get("/api/closed-bets")
async def get_closed_bets(limit: int = 100):
    """Get settled bets"""
    return db.get_closed_bets(limit)


@app.get("/api/signals")
async def get_signals(limit: int = 50):
    """Get recent signals"""
    return db.get_recent_signals(limit)


@app.get("/api/risk-status")
async def get_risk_status():
    """Get risk management status"""
    portfolio = db.get_portfolio()
    return risk_manager.get_risk_summary(portfolio)


@app.post("/api/reset-circuit-breaker")
async def reset_circuit_breaker():
    """Reset circuit breaker"""
    risk_manager.reset_circuit_breaker()
    return {"status": "ok", "message": "Circuit breaker reset"}


@app.get("/api/stats")
async def get_stats():
    """Get comprehensive statistics"""
    portfolio = db.get_portfolio()
    stats = db.get_stats()
    settlement_stats = settlement_engine.get_settlement_stats()
    risk_summary = risk_manager.get_risk_summary(portfolio)
    
    return {
        "portfolio": portfolio,
        "trading_stats": stats,
        "settlement_stats": settlement_stats,
        "risk_summary": risk_summary
    }


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    # Ensure directories exist
    Path(config.LOG_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(config.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    
    # Run server
    uvicorn.run(
        app,
        host=config.API_HOST,
        port=config.API_PORT,
        log_level="info"
    )
