"""Test cases for SettlementEngine."""

import pytest
from executor.settler import SettlementEngine


def test_settle_win():
    # Settle bet HIGH > 25.0 with actual temperature 27.0 => Win
    class DummyBet:
        strike_temp = 25.0
        bet_type = "YES"
        side = "HIGH"
        stake = 10.0
        entry_price = 0.5
        status = "active"

    engine = SettlementEngine(None)
    bet = DummyBet()
    res = engine.settle_bet(bet, 27.0)
    assert res["status"] == "won"
    assert res["realized_pnl"] == 10.0
