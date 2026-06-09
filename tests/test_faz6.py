"""Faz 6 tests: settlement engine, PnL calculation, portfolio update."""

import os
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)

from config.settings import config as _cfg
_cfg.DB_PATH = _db_path

import importlib
import database.db
importlib.reload(database.db)

from database.db import init_db, get_session
init_db()

from database.models import Bet, WeatherMarket, Portfolio


def _clean():
    with get_session() as session:
        session.query(Bet).delete()
        session.query(WeatherMarket).delete()
        session.query(Portfolio).delete()
        session.commit()


def _setup(market_type="HIGH", yes_price=0.35, threshold=30.0, side="YES"):
    _clean()
    yesterday = datetime.now() - timedelta(days=1)
    with get_session() as session:
        pf = Portfolio(
            id=1, cash_balance=990.0, total_value=1000.0,
            current_value=990.0, total_realized_pnl=0.0,
        )
        session.add(pf)
        market = WeatherMarket(
            id="test-settle-123", question="Will NYC temp exceed 30C?",
            city="New York", city_code="KLGA", metric="temperature_max",
            threshold=threshold, target_date=yesterday,
            yes_price=yes_price, no_price=round(1.0 - yes_price, 2),
            status="bet_placed", latitude=40.7128, longitude=-74.0060,
            market_type=market_type,
        )
        session.add(market)
        entry_price = yes_price if side == "YES" else round(1.0 - yes_price, 2)
        shares = 10.0 / entry_price if entry_price > 0 else 0
        bet = Bet(
            market_id="test-settle-123", side=side, amount=10.0,
            price=entry_price, entry_price=entry_price, shares=shares,
            status="placed", unrealized_pnl=0.0,
        )
        session.add(bet)
        session.commit()
    return market, bet, pf


def _mock_weather(actual_temp):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "daily": {
            "temperature_2m_max": [actual_temp],
            "temperature_2m_min": [actual_temp - 5],
        }
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def test_settle_win_yes():
    """YES bet wins when actual temp > strike (HIGH market)."""
    _setup(yes_price=0.35, threshold=30.0, side="YES")
    try:
        with patch("executor.settler.requests.get") as mock_get:
            mock_get.return_value = _mock_weather(32.0)
            from executor.settler import SettlementEngine
            engine = SettlementEngine()
            results = engine.settle_all()
            assert results["win"] == 1
            assert results["loss"] == 0
            assert results["total_pnl"] > 0
        with get_session() as session:
            bet_db = session.query(Bet).filter(
                Bet.market_id == "test-settle-123"
            ).first()
            assert bet_db.status == "won"
            assert bet_db.realized_pnl > 0
            pf_db = session.query(Portfolio).filter(Portfolio.id == 1).first()
            assert pf_db.cash_balance > 990.0
            assert pf_db.total_won == 1
            mkt = session.query(WeatherMarket).filter(
                WeatherMarket.id == "test-settle-123"
            ).first()
            assert mkt.status == "settled_win"
    finally:
        _clean()


def test_settle_loss_yes():
    """YES bet loses when actual temp < strike."""
    _setup(yes_price=0.35, threshold=30.0, side="YES")
    try:
        with patch("executor.settler.requests.get") as mock_get:
            mock_get.return_value = _mock_weather(28.0)
            from executor.settler import SettlementEngine
            engine = SettlementEngine()
            results = engine.settle_all()
            assert results["loss"] == 1
            assert results["win"] == 0
        with get_session() as session:
            bet_db = session.query(Bet).filter(
                Bet.market_id == "test-settle-123"
            ).first()
            assert bet_db.status == "lost"
            assert bet_db.realized_pnl < 0
            pf_db = session.query(Portfolio).filter(Portfolio.id == 1).first()
            assert pf_db.total_lost == 1
            mkt = session.query(WeatherMarket).filter(
                WeatherMarket.id == "test-settle-123"
            ).first()
            assert mkt.status == "settled_loss"
    finally:
        _clean()


def test_settle_win_no():
    """NO bet wins when actual temp > strike (NOT low)."""
    _setup(market_type="LOW", yes_price=0.65, threshold=30.0, side="NO")
    try:
        with patch("executor.settler.requests.get") as mock_get:
            mock_get.return_value = _mock_weather(35.0)
            from executor.settler import SettlementEngine
            engine = SettlementEngine()
            results = engine.settle_all()
            assert results["win"] == 1
            assert results["total_pnl"] > 0
        with get_session() as session:
            bet_db = session.query(Bet).filter(
                Bet.market_id == "test-settle-123"
            ).first()
            assert bet_db.status == "won"
            assert bet_db.realized_pnl > 0
    finally:
        _clean()


def test_no_markets_to_settle():
    """No markets past target_date -> returns 0."""
    _clean()
    try:
        with get_session() as session:
            future = datetime.now() + timedelta(days=7)
            mkt = WeatherMarket(
                id="test-future", question="Future", city="Test",
                metric="temperature_max", threshold=30.0,
                target_date=future, yes_price=0.50, no_price=0.50,
                status="open",
            )
            session.add(mkt)
            session.commit()
        from executor.settler import SettlementEngine
        engine = SettlementEngine()
        results = engine.settle_all()
        assert results["win"] == 0
        assert results["loss"] == 0
    finally:
        _clean()


def test_no_open_bets_market_expired():
    """Market past target_date but no bets -> market marked expired."""
    _clean()
    try:
        yesterday = datetime.now() - timedelta(days=1)
        with get_session() as session:
            mkt = WeatherMarket(
                id="test-no-bets", question="No bets", city="Test",
                metric="temperature_max", threshold=30.0,
                target_date=yesterday, yes_price=0.50, no_price=0.50,
                status="open",
            )
            session.add(mkt)
            session.commit()
        from executor.settler import SettlementEngine
        engine = SettlementEngine()
        engine.settle_all()
        with get_session() as session:
            mkt = session.query(WeatherMarket).filter(
                WeatherMarket.id == "test-no-bets"
            ).first()
            assert mkt.status == "expired"
    finally:
        _clean()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
