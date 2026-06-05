"""
SIA Loop - Self-Improving Algorithm (PolyTempAI)
DB'deki gercek settled bets sonuclarindan Brier Score ile ogrenir.
Bot surekli iyilesir.

Fix: session_factory pattern
Fix: BetStatus string values
Fix: datetime.now(timezone.utc) instead of datetime.now()
Fix: Neutral values when no settled bets (BUG 3)
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from database import ModelPerformance, Bet, close_db_session
from config import Config

logger = logging.getLogger("SIA_Loop")


class SIALoop:
    """Self-Improving Algorithm loop using Brier Score optimization."""
    def __init__(self, db_session_factory=None, config: Config = None):
        self.db_session_factory = db_session_factory
        self.config = config or Config()
        self.model_weights = self.config.MODEL_WEIGHTS.copy()

    def calculate_brier_score(
        self, predictions: List[float], outcomes: List[bool]
    ) -> float:
        """
        Brier Score hesapla (olasilik tahmini dogrulugu).
        Dusuk skor = Iyi tahmin.
        """
        if len(predictions) != len(outcomes) or len(predictions) == 0:
            return 1.0

        squared_errors = [
            (pred - (1.0 if outcome else 0.0)) ** 2
            for pred, outcome in zip(predictions, outcomes)
        ]

        brier_score = sum(squared_errors) / len(squared_errors)
        return round(brier_score, 4)

    def analyze_model_performance(self, days: int = 30) -> Dict[str, Dict]:
        """
        Her modelin son N gunluk performansini analiz et.
        BUG 3 fix: Use ALL settled bets with expected_value as prediction proxy.
        When no settled bets exist, return neutral performance (not random data).
        """
        performance = {}

        if not self.db_session_factory:
            # Fallback without DB: return neutral values
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
                    # BUG 3 fix: Use ALL settled bets (no random subsetting)
                    predictions = []
                    outcomes = []
                    for bet in settled_bets:
                        # Use expected_value as the model's prediction probability
                        pred = getattr(bet, "expected_value", None)
                        if pred is None or pred <= 0:
                            pred = getattr(bet, "entry_price", 0.5)
                        if pred is None or pred <= 0:
                            pred = 0.5
                        predictions.append(min(0.99, max(0.01, float(pred))))
                        outcome = getattr(bet, "realized_pnl", 0) > 0
                        outcomes.append(outcome)
                else:
                    # No data: return neutral values (BUG 3 fix - not random)
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
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Error analyzing model performance")
            return {}
        finally:
            close_db_session(db)

    def optimize_weights(self, performance_data: Dict[str, Dict]) -> Dict[str, float]:
        """
        Brier Score'a gore model agirliklarini optimize et.
        """
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
        """
        Tam optimizasyon dongusu calistir.
        """
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
            # Update Config MODEL_WEIGHTS for downstream consumers
            if hasattr(self.config, "MODEL_WEIGHTS"):  # pylint: disable=invalid-name
                setattr(self.config, "MODEL_WEIGHTS", new_weights)

            # Veritabanina kaydet
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

        except Exception as e:  # pylint: disable=broad-exception-caught
            db.rollback()
            logger.error("SIA Loop hatasi: %s", e, exc_info=True)
            return False
        finally:
            close_db_session(db)

    def get_adjusted_probability(
        self, base_prob: float, _model_name: str, recent_brier: float
    ) -> float:
        """
        Modelin son Brier Score'una gore olasiligi ayarla.
        """
        confidence_factor = 1.0 - (recent_brier * 0.5)
        confidence_factor = max(0.5, min(1.0, confidence_factor))
        adjusted_prob = 0.5 + (base_prob - 0.5) * confidence_factor
        return round(max(0.0, min(1.0, adjusted_prob)), 4)
