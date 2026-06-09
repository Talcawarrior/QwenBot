"""Faz 3: Analysis, Kelly, Risk, EV tests."""

import os
import tempfile
from datetime import datetime, timezone, timedelta

# Point to a temp DB for fresh tables
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)
from config.settings import config as _cfg
_cfg.DB_PATH = _db_path

from database.db import init_db
init_db()

from config.settings import config, bot_config


def test_fee_drag():
    """Test 1: FEE_DRAG must be 0.02."""
    assert config.FEE_DRAG == 0.02, f"FEE_DRAG={config.FEE_DRAG}, expected 0.02"
    assert bot_config.strategy.fee_drag == 0.02, (
        f"strategy.fee_drag={bot_config.strategy.fee_drag}, expected 0.02"
    )
    print("✅ Test 1: FEE_DRAG = 0.02")


def test_ev_with_fee():
    """Test 2: EV = edge - FEE_DRAG in analyze_signal."""
    from engine.strategy import BettingEngine
    be = BettingEngine()
    signal = be.analyze_signal(
        {"yes_price": 0.60, "city_code": "KLGA", "strike_temp": 30, "market_type": "HIGH"},
        model_prob=0.75,
        side="YES",
    )
    assert signal is not None
    # edge = 0.75 - 0.60 = 0.15, ev = 0.15 - 0.02 = 0.13
    assert abs(signal["edge"] - 0.15) < 0.001, f"edge={signal['edge']}"
    assert abs(signal["ev"] - 0.13) < 0.001, f"ev={signal['ev']}"
    print(f"✅ Test 2: EV={signal['ev']:.4f} (edge={signal['edge']:.4f} - FEE_DRAG)")


def test_kelly_bankroll():
    """Test 3: Calculator reads bankroll from DB."""
    # Set portfolio to $2000
    from database.db import get_session
    from database.models import Portfolio, WeatherMarket, WeatherForecast, Analysis
    from engine.calculator import Calculator

    with get_session() as session:
        pf = session.query(Portfolio).filter(Portfolio.id == 1).first()
        if not pf:
            pf = Portfolio(
                id=1, cash_balance=2000.0, current_value=2000.0,
                total_value=2000.0, initial_value=2000.0,
            )
            session.add(pf)
        else:
            pf.total_value = 2000.0
            pf.cash_balance = 2000.0
        session.commit()

    # Create a market + forecasts (METRIC_MAP already works per Faz 2)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    target = now + timedelta(days=2)
    with get_session() as session:
        m = WeatherMarket(
            id="test-faz3-bankroll",
            question="Test bankroll?",
            city="New York", city_code="KLGA",
            metric="temperature_max", threshold=30.0,
            target_date=target, yes_price=0.60, no_price=0.40,
            volume=1000, status="open", latitude=40.71, longitude=-74.0,
        )
        session.add(m)
        for src, val in [("gfs_seamless", 32.0), ("ecmwf_ifs04", 31.5)]:
            session.add(WeatherForecast(
                market_id="test-faz3-bankroll", city="New York",
                lat=40.71, lon=-74.0, target_date=target,
                metric="temperature_2m_max",
                source=src, predicted_value=val, model_weight=0.5,
                fetched_at=now,
            ))
        session.commit()

    calc = Calculator()
    orig_min_edge = bot_config.strategy.min_edge
    bot_config.strategy.min_edge = 0.005
    analysis_instance = calc.analyze_market("test-faz3-bankroll")
    bot_config.strategy.min_edge = orig_min_edge

    assert analysis_instance is not None, "Analysis is NULL"

    # Access attributes within session to avoid DetachedInstanceError
    with get_session() as session:
        analysis = session.query(Analysis).filter(
            Analysis.market_id == "test-faz3-bankroll"
        ).first()
        assert analysis is not None, "Analysis not found in DB!"
        rec_amount = analysis.recommended_amount
        assert rec_amount > 0, f"recommended_amount is {rec_amount}!"
        print(f"✅ Test 3: recommended_amount=${rec_amount:.2f} "
              f"(bankroll=$2000, max_bet=$50)")


def test_sia_status():
    """Test 4: SIALoop uses 'won'/'lost' not 'settled'."""
    from engine.strategy import SIALoop
    import inspect
    src = inspect.getsource(SIALoop.analyze_model_performance)
    assert '"won"' in src, "Missing 'won' in status filter"
    assert '"lost"' in src, "Missing 'lost' in status filter"
    assert '"settled"' not in src.replace('"won", "lost"', ''), (
        "'settled' should not be in status filter"
    )
    print("✅ Test 4: SIALoop uses 'won'/'lost' statuses")


def test_sia_brier_input():
    """Test 5: SIALoop uses fair_value (probability), not expected_value (edge)."""
    from engine.strategy import SIALoop
    import inspect
    src = inspect.getsource(SIALoop.analyze_model_performance)
    assert "fair_value" in src, "Missing fair_value in Brier input"
    # Verify the Brier prediction source line uses fair_value, not expected_value
    # (expected_value is an ORM field on Bet model — it appears elsewhere legitimately)
    assert "pred = getattr(bet, \"fair_value\", None)" in src, (
        "Brier input should use fair_value (probability), not expected_value (edge)"
    )
    assert "expected_value" not in [line for line in src.split("\n") if "pred =" in line][0], (
        "The prediction line should not reference expected_value"
    )
    print("✅ Test 5: SIALoop uses fair_value for Brier score")


def test_ladder_pending():
    """Test 6: Ladder orders start as PENDING."""
    from engine.strategy import BettingEngine
    be = BettingEngine()
    signal = {"market_price": 0.35, "edge": 0.06}
    ladder = be.create_ladder_orders(signal, 30.0)
    assert len(ladder) == 3, f"Expected 3 levels, got {len(ladder)}"
    for lvl in ladder:
        assert lvl["status"] == "pending", (
            f"Level {lvl['level']} status is '{lvl['status']}', expected 'pending'"
        )
        assert "filled_at" in lvl, f"Level {lvl['level']} missing 'filled_at'"
    print(f"✅ Test 6: Ladder pending OK — {ladder[0]['price']}, {ladder[1]['price']}, {ladder[2]['price']}")


def test_exposure_query():
    """Test 7: RiskManager.get_total_exposure uses Bet.amount."""
    from engine.strategy import RiskManager
    import inspect
    src = inspect.getsource(RiskManager.get_total_exposure)
    assert "Bet.amount" in src, "Missing Bet.amount in exposure query"
    print("✅ Test 7: RiskManager uses Bet.amount for exposure")


def test_risk_manager_init():
    """Test 8: RiskManager initializes without error."""
    from engine.strategy import RiskManager
    rm = RiskManager()
    assert rm.portfolio_value > 0
    print(f"✅ Test 8: RiskManager initialized, portfolio=${rm.portfolio_value}")


def test_betting_engine_ev_full():
    """Test 9: Full EV pipeline with fee."""
    from engine.strategy import BettingEngine
    be = BettingEngine()

    # Test with edge just above fee
    s1 = be.analyze_signal(
        {"yes_price": 0.70, "city_code": "KLGA"},
        model_prob=0.73, side="YES",
    )
    # edge=0.03, ev=0.01 → eligible (ev>0, edge>=min_edge=0.01)
    assert s1 is not None, "Should be eligible"
    assert s1["ev"] == 0.01, f"EV={s1['ev']}, expected 0.01"

    # Test with edge below fee
    s2 = be.analyze_signal(
        {"yes_price": 0.70, "city_code": "KLGA"},
        model_prob=0.71, side="YES",
    )
    # edge=0.01, ev=-0.01 → not eligible (ev must be > 0)
    assert s2 is None, "Should NOT be eligible (ev < 0)"
    print(f"✅ Test 9: EV pipeline OK — eligible edge={s1['edge']}->ev={s1['ev']}, "
          f"rejected edge=0.01->ev=-0.01")


if __name__ == "__main__":
    test_fee_drag()
    test_ev_with_fee()
    test_kelly_bankroll()
    test_sia_status()
    test_sia_brier_input()
    test_ladder_pending()
    test_exposure_query()
    test_risk_manager_init()
    test_betting_engine_ev_full()
    print("\n" + "=" * 50)
    print("ALL FAZ 3 TESTS PASSED ✅")
    print("=" * 50)
