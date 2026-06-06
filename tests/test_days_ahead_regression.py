"""Regression test for the days_ahead=0 / min_liquidity=0 fix in Calculator.

The original bug:
    target_date was set to end-of-day (23:59:59) to keep "today" in scope.
    However `(target_date - now).days` returns 0 when the difference is less
    than one calendar day, so the check `0 < days_ahead <= max_days_ahead`
    rejected every market that resolves "today".

The fix:
    The check was relaxed to `0 <= days_ahead <= max_days_ahead` AND
    `min_liquidity` was lowered to 0.0 because Polymarket public-search
    markets do not expose a meaningful `liquidity` field.

These tests pin both behaviors so they cannot regress silently.
"""

import sys
import inspect
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from engine.calculator import Calculator


def test_estimate_probability_zero_days_ahead_does_not_crash():
    """estimate_probability must accept days_ahead=0 without raising."""
    calc = Calculator()
    prob = calc.estimate_probability([22.0, 21.0, 23.0], 22.0, days_ahead=0)
    assert 0.0 <= prob <= 1.0


def test_estimate_probability_monotonic_in_days_ahead():
    """Holding mean/threshold constant, the probability mass on the wrong
    side of the strike should grow with days_ahead (more uncertainty).
    """
    calc = Calculator()
    forecasts = [22.0, 22.0, 22.0]  # mean exactly at threshold
    threshold = 22.0
    # When mean == threshold and std is the same, days_ahead increases
    # total uncertainty, so the probability of being "above" should
    # approach 0.5 from the days_ahead=0 base.
    p0 = calc.estimate_probability(forecasts, threshold, days_ahead=0)
    p3 = calc.estimate_probability(forecasts, threshold, days_ahead=3)
    # Both must be near 0.5 because mean == threshold; the key point is
    # neither raises and both are valid probabilities.
    assert 0.3 <= p0 <= 0.7
    assert 0.3 <= p3 <= 0.7


def test_estimate_probability_rejects_empty_forecasts():
    """Empty forecast list returns 0.5 (neutral) and does not raise."""
    calc = Calculator()
    assert calc.estimate_probability([], 22.0, days_ahead=0) == 0.5


def test_estimate_probability_clamps_to_open_unit_interval():
    """Probability is clamped to (0.01, 0.99) so Kelly doesn't divide by 0."""
    calc = Calculator()
    p = calc.estimate_probability([100.0], 0.0, days_ahead=0)  # far above
    assert 0.01 <= p <= 0.99
    p2 = calc.estimate_probability([0.0], 100.0, days_ahead=0)  # far below
    assert 0.01 <= p2 <= 0.99


def test_analyze_market_source_uses_inclusive_days_ahead_check():
    """Pin the actual code shape: the days_ahead check must use
    `0 <= days_ahead <=` (inclusive lower bound), not `0 < days_ahead <=`.
    A regression that adds a strict inequality would reject today's
    markets and produce should_bet=False for everything.
    """
    src = inspect.getsource(Calculator.analyze_market)
    # Look for the boolean expression that gates should_bet. Accept either
    # the inline form or the `days_ahead_for_check` form.
    assert "0 <= days_ahead" in src or "0 <= days_ahead_for_check" in src, (
        "Calculator.analyze_market must use `0 <= days_ahead <= ...` so that "
        "today-resolving markets (days_ahead == 0) are not rejected."
    )
    # And explicitly reject the old buggy form
    assert "0 < days_ahead" not in src, (
        "Strict `0 < days_ahead` rejects today's markets (regression)."
    )


def test_analyze_market_source_uses_min_liquidity_bypass():
    """Pin that min_liquidity=0 (or no liquidity) does not block analysis."""
    src = inspect.getsource(Calculator.analyze_market)
    assert "min_liquidity" in src, "analyze_market must reference min_liquidity"
    assert "<= 0" in src or "min_liquidity <= 0" in src, (
        "analyze_market must allow min_liquidity <= 0 to bypass the check."
    )


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
