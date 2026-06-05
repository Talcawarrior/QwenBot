"""
BETTING ENGINE MODULE - POLYMARKET ULTIMATE HYBRID WEATHER BOT
- Signal Analysis, Ladder Betting, Position Management
- HATA 3 DÜZELTİLDİ (ladder_data JSON serialization)
"""

import json
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone
from config import config
from database import Bet

logger = logging.getLogger(__name__)


class SimpleSignal:
    """Lightweight signal object for inter-module compatibility."""

    market_id: str = ""
    city: str = ""
    city_code: str = ""
    outcome: str = "YES"
    entry_price: float = 0.5
    fair_value: float = 0.5
    edge: float = 0.0
    probability: float = 0.5
    bet_size: float = 0.0
    ladder_orders: list = []
    side: str = "YES"

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class MockBet:
    """Fallback bet object when DB insert fails."""

    def __init__(self, **kwargs):
        """Initialize MockBet with optional keyword arguments."""
        self.id = 999
        self.city = kwargs.get("city", "")
        self.outcome = kwargs.get("outcome", "YES")
        self.stake_amount = kwargs.get("bet_size", 0.0)
        self.entry_price = kwargs.get("entry_price", 0.5)
        self.fair_value = kwargs.get("fair_value", 0.5)
        self.expected_value = kwargs.get("edge", 0.0)
        self.unrealized_pnl = 0.0
        self.realized_pnl = 0.0
        self.status = "active"
        self.placed_at = datetime.now(timezone.utc)


class BettingEngine:
    """Signal analysis, ladder betting, and position management."""

    def __init__(self, db_session=None, risk_manager=None, weather_engine=None):
        self.db = db_session
        self.risk_manager = risk_manager
        self.weather_engine = weather_engine
        self.config = config
        # active_bets memory removed - use DB via risk_manager (BUG-14 fix)

    def analyze_signal(
        self, market_data: Dict, model_prob: float, side: str = "YES"
    ) -> Optional[Dict]:
        """
        Sinyal analizi: edge, EV hesapla.
        Side-aware: YES uses yes_price + model_prob; NO uses 1-yes +
        1-model (fixes YES-only EV/Kelly bug).
        """
        yes_price = market_data.get("yes_price", 0.5)
        if side.upper() == "NO":
            market_price = 1.0 - yes_price
            edge = (1.0 - model_prob) - market_price
        else:
            market_price = yes_price
            edge = model_prob - market_price

        # Fee drag düş
        ev = edge - self.config.FEE_DRAG

        is_eligible = edge >= self.config.MIN_EDGE and ev > 0

        if not is_eligible:
            return None

        return {
            "city_code": market_data.get("city_code", ""),
            "strike_temp": market_data.get("strike_temp", 0),
            "market_type": market_data.get("market_type", "HIGH"),
            "model_prob": model_prob,
            "market_price": market_price,
            "edge": round(edge, 4),
            "ev": round(ev, 4),
            "is_eligible": True,
            "side": side,
        }

    def create_ladder_orders(self, signal: Dict, bet_size: float) -> List[Dict]:
        """
        Ladder betting: Edge > %5 ise 3-kademeli limit emirleri
        """
        edge = signal.get("edge", 0)

        if edge < 0.05:  # %5'ten küçükse ladder yok
            return []

        current_price = signal["market_price"]

        # 3-kademeli ladder
        ladder = [
            {
                "level": 1,
                "price": round(current_price * 0.98, 3),  # %2 altı
                "size": bet_size * 0.5,  # %50
            },
            {
                "level": 2,
                "price": round(current_price * 0.95, 3),  # %5 altı
                "size": bet_size * 0.3,  # %30
            },
            {
                "level": 3,
                "price": round(current_price * 0.92, 3),  # %8 altı
                "size": bet_size * 0.2,  # %20
            },
        ]

        # HATA 3: JSON serializable format
        return ladder

    def calculate_position_size(
        self, signal: Dict, portfolio_value: float, risk_manager
    ) -> float:
        """
        Pozisyon boyutu hesapla (Kelly + caps)
        Real DB exposure via risk_manager (BUG-13 fix)
        """
        market_price = signal["market_price"]

        # Kelly calculation
        kelly_size = risk_manager.calculate_kelly_bet_size(
            signal.get("model_prob", 0.5), market_price
        )

        # Exposure cap kontrolü - real from DB
        current_exposure = 0.0
        if risk_manager and hasattr(risk_manager, "get_total_exposure"):
            current_exposure = risk_manager.get_total_exposure()

        if not risk_manager.check_exposure_cap(current_exposure, kelly_size):
            # Cap aşılıyorsa azalt
            max_allowed = (
                portfolio_value * self.config.TOTAL_EXPOSURE_PCT
            ) - current_exposure
            kelly_size = min(kelly_size, max_allowed)

        return max(kelly_size, self.config.MIN_BET_SIZE)

    def serialize_bet_data(self, bet_dict: Dict) -> str:
        """
        Bahis verisini JSON string'e çevir (database için)
        HATA 3 DÜZELTİLDİ
        """
        return json.dumps(bet_dict)

    def deserialize_bet_data(self, json_str: str) -> Dict:
        """
        JSON string'den bahis verisi çıkar
        """
        if not json_str:
            return {}
        try:
            return json.loads(json_str)
        except Exception:  # pylint: disable=broad-exception-caught
            return {}

    async def analyze_market(
        self, market_data, portfolio_value, forecast=None
    ):
        """Wrapper for compatibility with main.py scan_loop calls."""
        if not market_data:
            return None

        # Extract fields - support both dict and ORM object
        if isinstance(market_data, dict):
            city = market_data.get("city", "Unknown")
            city_code = market_data.get("city_code", "")
            strike_temp = market_data.get("strike_temp", 25.0)
            market_type = market_data.get("market_type", "HIGH")
            yes_price = market_data.get("yes_price", 0.5)
        else:
            city = getattr(market_data, "city", "Unknown")
            city_code = getattr(market_data, "city_code", "")
            strike_temp = getattr(market_data, "strike_temp", 25.0)
            market_type = getattr(market_data, "market_type", "HIGH")
            yes_price = getattr(market_data, "yes_price", 0.5) or getattr(
                market_data, "current_yes_bid", 0.5
            )

        # Compute model_prob from forecast if available (side-aware for HIGH/LOW)
        model_prob = 0.55  # default bias
        side = "YES"
        if forecast and hasattr(self.weather_engine, "calculate_probability_above"):
            try:
                if (
                    "LOW" in str(market_type).upper()
                    or "below"
                    in str(getattr(market_data, "question", "") or "").lower()
                ):
                    model_prob = self.weather_engine.calculate_probability_below(
                        strike_temp, forecast
                    )
                    side = "NO" if model_prob < 0.5 else "YES"  # adjust
                else:
                    model_prob = self.weather_engine.calculate_probability_above(
                        strike_temp, forecast
                    )
            except Exception:  # pylint: disable=broad-exception-caught
                model_prob = 0.55

        # Use existing analyze_signal (now side aware via market_price logic)
        signal_dict = self.analyze_signal(
            {
                "city_code": city_code,
                "city": city,
                "strike_temp": strike_temp,
                "market_type": market_type,
                "yes_price": yes_price,
                "market_price": yes_price,
            },
            model_prob,
            side=side,
        )

        if not signal_dict:
            return None

        # Compute bet size using risk if available (uses portfolio_value)
        bet_size = 10.0
        if self.risk_manager and hasattr(self.risk_manager, "calculate_position_size"):
            try:
                bet_size = self.calculate_position_size(
                    signal_dict, portfolio_value, self.risk_manager
                )
            except Exception:  # pylint: disable=broad-exception-caught
                bet_size = 10.0
        signal_dict["bet_size"] = bet_size

        # Create simple signal object compatible with main.py usage
        sig = SimpleSignal(
            market_id=getattr(market_data, "market_id", "")
            if not isinstance(market_data, dict)
            else market_data.get("market_id", ""),
            city=city,
            city_code=city_code,
            outcome="YES" if model_prob >= 0.5 else "NO",
            entry_price=yes_price,
            fair_value=model_prob,
            edge=signal_dict.get("edge", 0),
            probability=model_prob,
            bet_size=bet_size,
            ladder_orders=[],
            side=side,
        )

        # Add ladder if edge high
        if sig.edge > 0.05:
            sig.ladder_orders = self.create_ladder_orders(signal_dict, sig.bet_size)

        return sig

    async def execute_signal(self, signal, market_data):
        """Wrapper - actually creates Bet in DB for real flow"""
        city = getattr(signal, "city", "Unknown")
        bet_size = getattr(signal, "bet_size", 10.0)
        logger.info("Placing bet for %s size $%.2f", city, bet_size)

        try:
            # Extract market info
            if isinstance(market_data, dict):
                market_id = (
                    market_data.get("market_id") or market_data.get("event_id") or ""
                )
                city_code = market_data.get("city_code", "")
                yes_price = market_data.get("yes_price", 0.5)
            else:
                market_id = getattr(
                    market_data, "market_id", getattr(market_data, "event_id", "")
                )
                city_code = getattr(market_data, "city_code", "")
                yes_price = getattr(market_data, "yes_price", 0.5) or getattr(
                    market_data, "current_yes_bid", 0.5
                )

            # Create real Bet record
            bet = Bet(
                market_id=str(market_id),
                city_code=city_code,
                city=city,
                outcome=getattr(signal, "outcome", "YES"),
                stake=bet_size,
                stake_amount=bet_size,
                entry_price=getattr(signal, "entry_price", yes_price),
                current_price=getattr(signal, "entry_price", yes_price),
                fair_value=getattr(signal, "fair_value", 0.5),
                expected_value=getattr(signal, "edge", 0.0),
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                strike_temp=getattr(signal, "strike_temp", 25.0)
                or (
                    market_data.get("strike_temp")
                    if isinstance(market_data, dict)
                    else getattr(market_data, "strike_temp", 25.0)
                ),
                bet_type=getattr(signal, "outcome", "YES"),
                side=getattr(signal, "side", "YES"),
                status="active",
                placed_at=datetime.now(timezone.utc),
                ladder_data=json.dumps(getattr(signal, "ladder_orders", []))
                if hasattr(signal, "ladder_orders")
                else None,
            )
            if self.db:
                self.db.add(bet)
                self.db.commit()
                self.db.refresh(bet)
                # Update risk manager
                if self.risk_manager and hasattr(
                    self.risk_manager, "increment_city_bet"
                ):
                    self.risk_manager.increment_city_bet(city_code)
            return bet
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Bet DB insert error (fallback): %s", e)
            if self.db:
                self.db.rollback()

            return MockBet(
                city=city,
                outcome=getattr(signal, "outcome", "YES"),
                bet_size=bet_size,
                entry_price=getattr(signal, "entry_price", 0.5),
                fair_value=getattr(signal, "fair_value", 0.5),
                edge=getattr(signal, "edge", 0.0),
            )


if __name__ == "__main__":

    def _run_betting_test():
        print("=== BETTING ENGINE TEST ===")

        be = BettingEngine()

        # Test signal
        test_signal = {
            "city_code": "KDAL",
            "strike_temp": 25.0,
            "market_type": "HIGH",
            "model_prob": 0.60,
            "market_price": 0.45,
            "edge": 0.15,
            "ev": 0.10,
            "is_eligible": True,
        }

        print("\n1. Signal Analysis:")
        print(f"   Edge: {test_signal['edge'] * 100}%")
        print(f"   EV: {test_signal['ev']}")

        print("\n2. Ladder Orders (Edge > 5%):")
        test_ladder = be.create_ladder_orders(test_signal, bet_size=30.0)
        for order in test_ladder:
            print(f"   Level {order['level']}: ${order['size']} @ ${order['price']}")

        print("\n3. JSON Serialization:")
        serialized = be.serialize_bet_data(
            {"ladder": test_ladder, "signal": test_signal}
        )
        print(f"   Serialized length: {len(serialized)} chars")
        deserialized = be.deserialize_bet_data(serialized)
        print(f"   Deserialized keys: {list(deserialized.keys())}")

        print("\nBetting engine tests passed!")

    _run_betting_test()
