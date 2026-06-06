"""Sinyal analizi, Kelly kasa yönetimi, risk kontrolü ve SIA kendi kendini geliştiren algoritma (Self-Improving Algorithm)."""

import json
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy import func
from config.settings import config
from database.models import Bet, Portfolio, ModelPerformance

logger = logging.getLogger("STRATEGY_ENGINE")


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


class RiskManager:
    """Risk management with Kelly sizing, smart pool, and circuit breakers."""

    def __init__(self, db_session=None, cfg=None):
        self.db = db_session
        self.config = cfg or config
        self.portfolio_value = getattr(self.config, "INITIAL_PORTFOLIO", 1000.0)
        self.daily_pnl = 0.0
        self.open_bets_count = 0
        self.city_bet_counts: Dict[str, int] = {}
        self._load_from_db()

    def update_portfolio(self, value: float):
        """Update portfolio value."""
        self.portfolio_value = value

    def update_daily_pnl(self, pnl: float):
        """Update daily PnL and check circuit breaker."""
        self.daily_pnl = pnl
        if self.daily_pnl <= -self.config.daily_loss_limit_amount:
            logger.warning("DAILY STOP-LOSS TRIGGERED! PnL: $%.2f", self.daily_pnl)
            return False
        return True

    def check_city_cap(self, city_code: str) -> bool:
        """Check city cap limit."""
        current_count = self.city_bet_counts.get(city_code, 0)
        return current_count < self.config.CITY_CAP

    def increment_city_bet(self, city_code: str):
        """Increment city bet count."""
        self.city_bet_counts[city_code] = self.city_bet_counts.get(city_code, 0) + 1

    def decrement_city_bet(self, city_code: str):
        """Decrement city bet count."""
        if city_code in self.city_bet_counts:
            self.city_bet_counts[city_code] = max(0, self.city_bet_counts[city_code] - 1)

    def calculate_kelly_bet_size(self, model_prob: float, market_price: float) -> float:
        """Calculate Kelly bet sizing."""
        if model_prob <= 0 or market_price <= 0 or market_price >= 1:
            return 0.0

        if model_prob >= 1.0:
            model_prob = 0.99

        b = (1 - market_price) / market_price
        p = model_prob
        q = 1 - p

        kelly_fraction = (b * p - q) / b if b > 0 else 0
        fractional_kelly = kelly_fraction * self.config.KELLY_FRACTION

        if fractional_kelly <= 0:
            return 0.0

        bet_amount = self.portfolio_value * fractional_kelly
        bet_amount = max(bet_amount, self.config.MIN_BET_SIZE)

        max_bet = self.portfolio_value * self.config.MAX_BET_PCT
        bet_amount = min(bet_amount, max_bet)

        return round(bet_amount, 2)

    def check_exposure_cap(self, current_exposure: float, additional_bet: float) -> bool:
        """Check total exposure cap limit."""
        max_exposure = self.portfolio_value * self.config.TOTAL_EXPOSURE_PCT
        return (current_exposure + additional_bet) <= max_exposure

    def is_bot_locked(self) -> bool:
        """Check if bot is locked."""
        return self.daily_pnl <= -self.config.daily_loss_limit_amount

    def get_daily_pnl(self) -> float:
        """Get daily PnL."""
        return self.daily_pnl

    def get_total_exposure(self) -> float:
        """Get total exposure (sum of `amount` for all open/active/placed bets)."""
        if self.db:
            try:
                # Include all open-style statuses so freshly-placed bets are
                # counted in exposure. "placed" is what BetPlacer writes
                # immediately after writing the Bet row. Use `Bet.amount`
                # (the column BetPlacer actually writes) rather than the
                # legacy `stake_amount` which stays at 0.
                total = (
                    self.db.query(func.coalesce(func.sum(Bet.amount), 0.0))
                    .filter(Bet.status.in_(["active", "open", "placed", "pending"]))
                    .scalar()
                )
                return float(total or 0.0)
            except Exception:
                pass
        exposure = sum(self.city_bet_counts.values()) * 20.0
        return exposure

    def get_portfolio_value(self) -> float:
        """Get portfolio value."""
        return self.portfolio_value

    def _load_from_db(self):
        """Load state from DB."""
        if not self.db:
            return
        try:
            portfolio = self.db.query(Portfolio).filter(Portfolio.id == 1).first()
            if portfolio:
                self.portfolio_value = (
                    portfolio.current_value
                    or portfolio.initial_value
                    or self.portfolio_value
                )
                self.daily_pnl = portfolio.daily_pnl or 0.0

            active = self.db.query(Bet).filter(Bet.status.in_(["active", "open"])).all()
            self.city_bet_counts = {}
            self.open_bets_count = len(active)
            for bet in active:
                cc = bet.city_code or "unknown"
                self.city_bet_counts[cc] = self.city_bet_counts.get(cc, 0) + 1
        except Exception as e:
            logger.warning("Risk load from DB warning: %s", e)


class BettingEngine:
    """Signal analysis, ladder betting, and position management."""

    def __init__(self, db_session=None, risk_manager=None, weather_engine=None):
        self.db = db_session
        self.risk_manager = risk_manager
        self.weather_engine = weather_engine
        self.config = config

    def analyze_signal(self, market_data: Dict, model_prob: float, side: str = "YES") -> Optional[Dict]:
        """Analyze signal, calculate edge and EV."""
        yes_price = market_data.get("yes_price", 0.5)
        if side.upper() == "NO":
            market_price = 1.0 - yes_price
            edge = (1.0 - model_prob) - market_price
        else:
            market_price = yes_price
            edge = model_prob - market_price

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
        """Create 3-level ladder orders if edge > 5%."""
        edge = signal.get("edge", 0)
        if edge < 0.05:
            return []

        current_price = signal["market_price"]
        ladder = [
            {"level": 1, "price": round(current_price * 0.98, 3), "size": bet_size * 0.5},
            {"level": 2, "price": round(current_price * 0.95, 3), "size": bet_size * 0.3},
            {"level": 3, "price": round(current_price * 0.92, 3), "size": bet_size * 0.2},
        ]
        return ladder

    def calculate_position_size(self, signal: Dict, portfolio_value: float, risk_manager) -> float:
        """Calculate position size using fractional Kelly and exposure caps."""
        market_price = signal["market_price"]
        kelly_size = risk_manager.calculate_kelly_bet_size(
            signal.get("model_prob", 0.5), market_price
        )

        current_exposure = 0.0
        if risk_manager and hasattr(risk_manager, "get_total_exposure"):
            current_exposure = risk_manager.get_total_exposure()

        if not risk_manager.check_exposure_cap(current_exposure, kelly_size):
            max_allowed = (portfolio_value * self.config.TOTAL_EXPOSURE_PCT) - current_exposure
            kelly_size = min(kelly_size, max_allowed)

        return max(kelly_size, self.config.MIN_BET_SIZE)

    async def analyze_market(self, market_data, portfolio_value, forecast=None):
        """Wrapper for analyzing a specific market."""
        if not market_data:
            return None

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

        model_prob = 0.55
        side = "YES"
        if forecast and hasattr(self.weather_engine, "calculate_probability_above"):
            try:
                if (
                    "LOW" in str(market_type).upper()
                    or "below" in str(getattr(market_data, "question", "") or "").lower()
                ):
                    model_prob = self.weather_engine.calculate_probability_below(
                        strike_temp, forecast
                    )
                    side = "NO" if model_prob < 0.5 else "YES"
                else:
                    model_prob = self.weather_engine.calculate_probability_above(
                        strike_temp, forecast
                    )
            except Exception:
                model_prob = 0.55

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

        bet_size = 10.0
        if self.risk_manager and hasattr(self.risk_manager, "calculate_position_size"):
            try:
                bet_size = self.calculate_position_size(
                    signal_dict, portfolio_value, self.risk_manager
                )
            except Exception:
                bet_size = 10.0
        signal_dict["bet_size"] = bet_size

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

        if sig.edge > 0.05:
            sig.ladder_orders = self.create_ladder_orders(signal_dict, sig.bet_size)

        return sig

    async def execute_signal(self, signal, market_data):
        """Wrapper for placing a simulated/paper bet."""
        city = getattr(signal, "city", "Unknown")
        bet_size = getattr(signal, "bet_size", 10.0)
        logger.info("Placing bet for %s size $%.2f", city, bet_size)

        try:
            if isinstance(market_data, dict):
                market_id = market_data.get("market_id") or market_data.get("event_id") or ""
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
                if self.risk_manager and hasattr(self.risk_manager, "increment_city_bet"):
                    self.risk_manager.increment_city_bet(city_code)
            return bet
        except Exception as e:
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


class SIALoop:
    """Self-Improving Algorithm loop using Brier Score optimization."""

    def __init__(self, db_session_factory=None, cfg=None):
        self.db_session_factory = db_session_factory
        self.config = cfg or config
        self.model_weights = self.config.MODEL_WEIGHTS.copy()

    def calculate_brier_score(self, predictions: List[float], outcomes: List[bool]) -> float:
        """Calculate Brier Score."""
        if len(predictions) != len(outcomes) or len(predictions) == 0:
            return 1.0

        squared_errors = [
            (pred - (1.0 if outcome else 0.0)) ** 2
            for pred, outcome in zip(predictions, outcomes)
        ]
        brier_score = sum(squared_errors) / len(squared_errors)
        return round(brier_score, 4)

    def analyze_model_performance(self, days: int = 30) -> Dict[str, Dict]:
        """Analyze performance of each model over recent days."""
        performance = {}

        if not self.db_session_factory:
            for model_name in self.model_weights.keys():
                performance[model_name] = {
                    "brier_score": 0.25,
                    "accuracy": 0.5,
                    "num_predictions": 0,
                    "avg_confidence": 0.5,
                }
            return performance

        db = self.db_session_factory()
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            settled_bets = (
                db.query(Bet)
                .filter(
                    Bet.status.in_(["settled", "won", "lost"]),
                    Bet.settled_at >= cutoff,
                )
                .all()
            )

            for model_name in self.model_weights.keys():
                if settled_bets:
                    predictions = []
                    outcomes = []
                    for bet in settled_bets:
                        pred = getattr(bet, "expected_value", None)
                        if pred is None or pred <= 0:
                            pred = getattr(bet, "entry_price", 0.5)
                        if pred is None or pred <= 0:
                            pred = 0.5
                        predictions.append(min(0.99, max(0.01, float(pred))))
                        outcome = getattr(bet, "realized_pnl", 0) > 0
                        outcomes.append(outcome)
                else:
                    performance[model_name] = {
                        "brier_score": 0.25,
                        "accuracy": 0.5,
                        "num_predictions": 0,
                        "avg_confidence": 0.5,
                    }
                    continue

                brier_score = self.calculate_brier_score(predictions, outcomes)
                correct = sum(
                    1
                    for pred, out in zip(predictions, outcomes)
                    if (pred >= 0.5) == out
                )
                accuracy = correct / len(predictions) if predictions else 0

                performance[model_name] = {
                    "brier_score": brier_score,
                    "accuracy": round(accuracy, 4),
                    "num_predictions": len(predictions),
                    "avg_confidence": round(sum(predictions) / len(predictions), 4)
                    if predictions
                    else 0,
                }
            return performance
        except Exception:
            logger.exception("Error analyzing model performance")
            return {}
        finally:
            db.close()

    def optimize_weights(self, performance_data: Dict[str, Dict]) -> Dict[str, float]:
        """Optimize model weights according to Brier Scores."""
        new_weights = {}
        inverse_scores = {
            model: max(0.01, 1.0 - data["brier_score"])
            for model, data in performance_data.items()
        }
        total = sum(inverse_scores.values())

        if total > 0:
            for model, score in inverse_scores.items():
                new_weights[model] = round(score / total, 4)
        else:
            n_models = len(self.model_weights)
            new_weights = {
                model: round(1.0 / n_models, 4) for model in self.model_weights
            }

        logger.info("SIA OPTIMIZASYONU:")
        for model, weight in new_weights.items():
            old_weight = self.model_weights.get(model, 0)
            change = weight - old_weight
            arrow = "^" if change > 0 else "v" if change < 0 else "="
            logger.info(
                "  %s: %.2f%% %s %.2f%% (%+.2f%%)",
                model,
                old_weight * 100,
                arrow,
                weight * 100,
                change * 100,
            )
        return new_weights

    def run_optimization_cycle(self) -> bool:
        """Execute full optimization cycle."""
        if not self.db_session_factory:
            logger.error("No db_session_factory, cannot run optimization")
            return False

        db = self.db_session_factory()
        try:
            logger.info("SIA Loop baslatiliyor...")
            performance = self.analyze_model_performance(days=30)
            sorted_models = sorted(
                performance.items(), key=lambda x: x[1]["brier_score"]
            )
            best_model = sorted_models[0][0]
            worst_model = sorted_models[-1][0]

            logger.info(
                "En iyi model: %s (Brier: %.4f)",
                best_model,
                performance[best_model]["brier_score"],
            )
            logger.info(
                "En kotu model: %s (Brier: %.4f)",
                worst_model,
                performance[worst_model]["brier_score"],
            )

            new_weights = self.optimize_weights(performance)
            self.model_weights = new_weights
            if hasattr(self.config, "MODEL_WEIGHTS"):
                setattr(self.config, "MODEL_WEIGHTS", new_weights)

            for model_name, perf in performance.items():
                record = ModelPerformance(
                    model_name=model_name,
                    brier_score=perf["brier_score"],
                    accuracy=perf["accuracy"],
                    num_predictions=perf["num_predictions"],
                    weight=new_weights.get(model_name, 0),
                    recorded_at=datetime.now(timezone.utc),
                )
                db.add(record)

            db.commit()
            logger.info("SIA Loop tamamlandi. Agirliklar guncellendi.")
            return True
        except Exception as e:
            db.rollback()
            logger.error("SIA Loop hatasi: %s", e, exc_info=True)
            return False
        finally:
            db.close()

    def get_adjusted_probability(
        self, base_prob: float, _model_name: str, recent_brier: float
    ) -> float:
        """Adjust base probability based on recent model Brier Score."""
        confidence_factor = 1.0 - (recent_brier * 0.5)
        confidence_factor = max(0.5, min(1.0, confidence_factor))
        adjusted_prob = 0.5 + (base_prob - 0.5) * confidence_factor
        return round(max(0.0, min(1.0, adjusted_prob)), 4)
