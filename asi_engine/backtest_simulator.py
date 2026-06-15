"""Backtest Simulator for ASIAbot.

Simulates the performance of proposed model weights and strategy parameters 
over the historical bets and analyses saved in the SQLite database.
"""

import json
import logging
from database.db import get_session
from database.models import Bet, Analysis, WeatherMarket
from utils.kelly import kelly_bet_amount

logger = logging.getLogger("ASI_BACKTESTER")


class BacktestSimulator:
    """Evaluates strategy parameters over historical operations in SQLite."""

    def run_backtest(self, parameters: dict) -> dict:
        """Run a backtest using the proposed model weights and parameters.

        Recalculates the consensus probabilities, checks if bets would have 
        been opened, sizes them with Kelly, and reports overall metrics.
        """
        model_weights = parameters["model_weights"]
        min_edge = parameters["min_edge"]
        kelly_fraction = parameters["kelly_fraction"]

        logger.info("ASI Backtester: Starting simulation over database records...")

        simulated_pnl = 0.0
        total_bets_opened = 0
        bets_won = 0
        bets_lost = 0
        total_wagered = 0.0
        brier_errors = []

        with get_session() as session:
            # Query all settled bets with their analysis & market details
            settled_records = (
                session.query(Bet, Analysis, WeatherMarket)
                .join(Analysis, Bet.analysis_id == Analysis.id, isouter=True)
                .join(WeatherMarket, Bet.market_id == WeatherMarket.id, isouter=True)
                .filter(Bet.status.in_(["won", "lost"]))
                .all()
            )

            if not settled_records:
                logger.warning("ASI Backtester: No historical settled bets found in DB. Returning neutral baseline.")
                return {
                    "brier_score": 0.25,
                    "roi": 0.0,
                    "win_rate": 0.0,
                    "total_bets": 0,
                    "pnl": 0.0
                }

            # Initialize a virtual bankroll starting at $1000
            bankroll = 1000.0

            for bet, analysis, market in settled_records:
                if not analysis or not analysis.model_predictions:
                    continue

                try:
                    mp = json.loads(analysis.model_predictions)
                except Exception:
                    continue

                model_probs = mp.get("model_probs", {})
                if not model_probs:
                    continue

                # 1. Recalculate consensus probability using proposed model weights
                weight_sum = sum(model_weights.get(m, 0.0) for m in model_probs)
                if weight_sum <= 0:
                    continue

                recalculated_prob = sum(
                    model_weights.get(m, 0.0) * float(prob)
                    for m, prob in model_probs.items()
                ) / weight_sum

                # 2. Check if the market outcome matches the YES direction
                # SIALoop resolve method helper:
                outcome_yes = self._resolve_outcome(market)
                if outcome_yes is None:
                    continue

                # Add to Brier Score calculation (YES probability vs actual outcome)
                brier_errors.append((recalculated_prob - (1.0 if outcome_yes else 0.0)) ** 2)

                # 3. Simulate bet eligibility and sizing
                # Check YES edge vs NO edge
                yes_price = float(market.yes_price or 0.5)
                no_price = 1.0 - yes_price

                yes_edge = recalculated_prob - yes_price
                no_edge = (1.0 - recalculated_prob) - no_price

                # Determine side and edge
                if yes_edge > no_edge:
                    sim_side = "YES"
                    sim_edge = yes_edge
                    entry_price = yes_price
                else:
                    sim_side = "NO"
                    sim_edge = no_edge
                    entry_price = no_price

                # Check if edge exceeds proposed min_edge (plus 2% fee_drag)
                ev = sim_edge - 0.02
                if sim_edge >= min_edge and ev > 0:
                    # Yes, would place a bet!
                    total_bets_opened += 1
                    
                    # Kelly size it
                    prob_win = recalculated_prob if sim_side == "YES" else (1.0 - recalculated_prob)
                    bet_size = kelly_bet_amount(
                        bankroll,
                        prob_win,
                        entry_price,
                        fraction=kelly_fraction,
                        min_bet=1.0,
                        max_bet_pct=0.03
                    )

                    # Evaluate bet outcome
                    won = (sim_side == "YES" and outcome_yes) or (sim_side == "NO" and not outcome_yes)
                    total_wagered += bet_size

                    if won:
                        bets_won += 1
                        payout = bet_size / entry_price
                        fee = payout * 0.02
                        pnl = payout - bet_size - fee
                    else:
                        bets_lost += 1
                        pnl = -bet_size

                    simulated_pnl += pnl
                    bankroll += pnl

        # Compile metrics
        final_brier = sum(brier_errors) / len(brier_errors) if brier_errors else 0.25
        roi = (simulated_pnl / total_wagered * 100) if total_wagered > 0 else 0.0
        win_rate = (bets_won / total_bets_opened) if total_bets_opened > 0 else 0.0

        logger.info("  Backtest Results -> Brier=%.4f, ROI=%.2f%%, Opened Bets=%d",
                    final_brier, roi, total_bets_opened)

        return {
            "brier_score": round(final_brier, 4),
            "roi": round(roi, 2),
            "win_rate": round(win_rate, 4),
            "total_bets": total_bets_opened,
            "pnl": round(simulated_pnl, 2)
        }

    @staticmethod
    def _resolve_outcome(market) -> bool | None:
        if market is None:
            return None
        raw = getattr(market, "raw_data", None)
        if not raw:
            return None
        try:
            rd = json.loads(raw) if isinstance(raw, str) else raw
            outcome = rd.get("outcome", "")
            if outcome == "YES":
                return True
            if outcome == "NO":
                return False
        except Exception:
            pass
        return None
