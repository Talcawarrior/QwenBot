import json
import random
from datetime import UTC, datetime, timedelta

from config.settings import bot_config, config
from database.db import ensure_initial_portfolio, get_session, init_db
from database.models import Analysis, Bet, Portfolio, WeatherMarket
from engine.strategy import SIALoop


def generate_historical_data():
    print("Initializing database...")
    init_db()
    ensure_initial_portfolio()

    # Clear previous operational data to ensure a clean simulation
    with get_session() as session:
        session.query(Bet).delete()
        session.query(Analysis).delete()
        session.query(WeatherMarket).delete()

        # Reset portfolio
        pf = session.query(Portfolio).filter(Portfolio.id == 1).first()
        if pf:
            pf.cash_balance = 1000.0
            pf.initial_value = 1000.0
            pf.current_value = 1000.0
            pf.total_value = 1000.0
            pf.total_realized_pnl = 0.0
            pf.daily_pnl = 0.0
            pf.total_won = 0
            pf.total_lost = 0
        session.commit()

    print("Generating 50 past bets with detailed historical metrics...")

    # 8 standard models of QwenBot
    model_names = [
        "gfs_seamless",
        "ecmwf_ifs04",
        "gem_seamless",
        "icon_seamless",
        "jma_msm",
        "cma_grapes_global",
        "ukmo_seamless",
        "meteofrance_seamless",
    ]

    cities = [
        ("Miami", "KMIA"),
        ("Dallas", "KDAL"),
        ("New York", "KLGA"),
        ("Chicago", "KORD"),
        ("Los Angeles", "KLAX"),
        ("Ankara", "LTAC"),
        ("Istanbul", "LTFM"),
        ("London", "EGLL"),
        ("Paris", "LFPG"),
        ("Tokyo", "RJTT"),
    ]

    now = datetime.now(UTC).replace(tzinfo=None)

    total_realized_pnl = 0.0
    won_count = 0
    lost_count = 0

    with get_session() as session:
        for i in range(50):
            market_id = f"hist-mkt-{i + 1:03d}"
            city, city_code = cities[i % len(cities)]

            # Decide the true resolution outcome (70% YES, 30% NO)
            outcome = "YES" if (i % 10 < 7) else "NO"

            # Setup the past market
            target_date = now - timedelta(days=random.randint(1, 5))
            market = WeatherMarket(
                id=market_id,
                question=f"Will the temperature in {city} exceed 30C?",
                city=city,
                city_code=city_code,
                threshold=30.0,
                target_date=target_date,
                yes_price=0.60,
                no_price=0.40,
                volume=1500.0,
                liquidity=800.0,
                status="settled_win" if outcome == "YES" else "settled_loss",
                raw_data=json.dumps(
                    {
                        "source": "polymarket",
                        "outcome": outcome,
                        "outcomePrices": [1.0, 0.0] if outcome == "YES" else [0.0, 1.0],
                        "umaResolutionStatus": "resolved",
                        "settled_at": (target_date + timedelta(hours=2)).isoformat(),
                    }
                ),
            )
            session.add(market)
            session.flush()  # Populate ID

            # Set model predictions
            # Accurate models (e.g. gfs_seamless, ecmwf_ifs04) will have probabilities aligned with outcome.
            # Inaccurate models (e.g. meteofrance_seamless) will have inverse/bad probabilities.
            model_probs = {}
            for m_name in model_names:
                if m_name == "gfs_seamless":
                    # High accuracy
                    prob = random.uniform(0.75, 0.95) if outcome == "YES" else random.uniform(0.05, 0.25)
                elif m_name == "ecmwf_ifs04":
                    # High accuracy
                    prob = random.uniform(0.70, 0.90) if outcome == "YES" else random.uniform(0.10, 0.30)
                elif m_name == "meteofrance_seamless":
                    # Low accuracy/inverse
                    prob = random.uniform(0.15, 0.35) if outcome == "YES" else random.uniform(0.65, 0.85)
                else:
                    # Random/average accuracy
                    prob = random.uniform(0.40, 0.70) if outcome == "YES" else random.uniform(0.30, 0.60)
                model_probs[m_name] = round(prob, 4)

            # Create Analysis
            est_prob = model_probs["gfs_seamless"]  # Use accurate model's prob as estimated
            analysis = Analysis(
                market_id=market_id,
                estimated_probability=est_prob,
                market_implied_prob=0.60 if outcome == "YES" else 0.40,
                edge=est_prob - 0.60,
                avg_forecast_value=32.0,
                std_forecast_value=1.5,
                num_sources=8,
                recommended_side="YES" if est_prob >= 0.5 else "NO",
                recommended_amount=15.0,
                should_bet=True,
                reason="SIA Historical Simulation",
                model_predictions=json.dumps(
                    {"model_temps": dict.fromkeys(model_names, 32.0), "model_probs": model_probs}
                ),
                analyzed_at=target_date - timedelta(hours=1),
            )
            session.add(analysis)
            session.flush()  # Populate ID

            # Decide Bet direction (we bet YES in most cases, or NO in some)
            side = "YES" if (i % 5 != 0) else "NO"
            bet_won = side == outcome
            status = "won" if bet_won else "lost"

            amount = 20.0
            price = 0.60 if side == "YES" else 0.40

            if bet_won:
                won_count += 1
                payout = amount / price
                fee = payout * 0.02
                pnl = payout - amount - fee
            else:
                lost_count += 1
                pnl = -amount

            total_realized_pnl += pnl

            # Create Bet
            bet = Bet(
                market_id=market_id,
                analysis_id=analysis.id,
                city_code=city_code,
                city=city,
                side=side,
                outcome=outcome,
                amount=amount,
                price=price,
                entry_price=price,
                shares=amount / price,
                fair_value=est_prob,
                expected_value=est_prob - price,
                status=status,
                pnl=round(pnl, 2),
                realized_pnl=round(pnl, 2),
                placed_at=target_date - timedelta(minutes=30),
                settled_at=target_date + timedelta(hours=3),
            )
            session.add(bet)

        # Update Portfolio metrics
        pf = session.query(Portfolio).filter(Portfolio.id == 1).first()
        pf.total_realized_pnl = round(total_realized_pnl, 2)
        pf.cash_balance = round(1000.0 + total_realized_pnl, 2)
        pf.current_value = pf.cash_balance
        pf.total_value = pf.cash_balance
        pf.total_won = won_count
        pf.total_lost = lost_count

        session.commit()

    print("Successfully generated 50 bets:")
    print(f"  - Won bets: {won_count}")
    print(f"  - Lost bets: {lost_count}")
    print(f"  - Net Realized PnL: ${total_realized_pnl:+.2f}")
    print(f"  - Final Cash Balance: ${1000.0 + total_realized_pnl:.2f}")


def run_sia_optimization():
    print("\nRunning SIA (Self-Improving Algorithm) Loop on the historical bets...")

    # Initialize SIALoop with correct db session factory
    from database.db import get_db_session_factory

    sia = SIALoop(db_session_factory=get_db_session_factory(), cfg=config)

    # Check default weights first
    print("\nOriginal weights in memory:")
    for m, w in sia.model_weights.items():
        print(f"  {m}: {w * 100:.2f}%")

    print("\nOriginal strategy parameters in memory:")
    print(f"  min_edge: {bot_config.strategy.min_edge:.4f}")
    print(f"  kelly_fraction: {bot_config.strategy.kelly_fraction:.4f}")

    # Run the cycle!
    success = sia.run_optimization_cycle()
    print(f"\nOptimization cycle executed successfully: {success}")

    # Inspect the results
    print("\nOptimized weights loaded from data/model_weights.json:")
    with open("data/model_weights.json") as f:
        new_weights = json.load(f)
        for m, w in new_weights.items():
            print(f"  {m}: {w * 100:.2f}%")

    print("\nOptimized strategy parameters loaded from data/strategy_params.json:")
    with open("data/strategy_params.json") as f:
        new_params = json.load(f)
        print(f"  min_edge: {new_params.get('min_edge')}")
        print(f"  kelly_fraction: {new_params.get('kelly_fraction')}")


if __name__ == "__main__":
    generate_historical_data()
    run_sia_optimization()
