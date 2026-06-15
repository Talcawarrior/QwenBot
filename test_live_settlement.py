import json
from datetime import datetime, timezone
from database.db import get_session
from database.models import WeatherMarket, Bet, Portfolio
from executor.settler import SettlementEngine

def run_live_settlement_test():
    print("Setting up live market 2513866 with 'bet_placed' status...")
    with get_session() as session:
        # Find the market in DB or insert it
        market = session.query(WeatherMarket).filter(WeatherMarket.id == "2513866").first()
        if not market:
            print("Market 2513866 not found in DB! Let's insert it first.")
            market = WeatherMarket(
                id="2513866",
                question="Will the highest temperature in Seoul be 19C or below on June 14?",
                city="Seoul",
                city_code="RKSS",
                target_date=datetime(2026, 6, 13, 23, 59, 59),
                yes_price=0.01,
                no_price=0.99,
                status="bet_placed"
            )
            session.add(market)
        else:
            market.status = "bet_placed"
            market.target_date = datetime(2026, 6, 13, 23, 59, 59)
            print("Market 2513866 updated to status 'bet_placed'.")

        # Create a paper bet on YES for this market
        # So we expect it to LOSE (since outcome is NO)
        # Delete existing bets on this market first to avoid duplicates
        session.query(Bet).filter(Bet.market_id == "2513866").delete()
        
        bet_yes = Bet(
            market_id="2513866",
            side="YES",
            amount=10.0,
            price=0.20,
            entry_price=0.20,
            shares=50.0,
            status="placed"
        )
        session.add(bet_yes)

        # Create a paper bet on NO for this market
        # So we expect it to WIN (since outcome is NO)
        bet_no = Bet(
            market_id="2513866",
            side="NO",
            amount=10.0,
            price=0.80,
            entry_price=0.80,
            shares=12.5,
            status="placed"
        )
        session.add(bet_no)
        session.commit()

    print("Running SettlementEngine to fetch real closing data from Polymarket Gamma API...")
    engine = SettlementEngine()
    results = engine.settle_all()

    print("\nSettlement Results:")
    print(f"  - Wins: {results.get('win')}")
    print(f"  - Losses: {results.get('loss')}")
    print(f"  - Pending: {results.get('pending')}")
    print(f"  - Total PnL: ${results.get('total_pnl'):+.2f}")

    with get_session() as session:
        mkt = session.query(WeatherMarket).filter(WeatherMarket.id == "2513866").first()
        b_yes = session.query(Bet).filter(Bet.market_id == "2513866", Bet.side == "YES").first()
        b_no = session.query(Bet).filter(Bet.market_id == "2513866", Bet.side == "NO").first()
        pf = session.query(Portfolio).filter(Portfolio.id == 1).first()

        print("\nDatabase Check after Settlement:")
        print(f"  - Market 2513866 Status: {mkt.status}")
        print(f"  - Market 2513866 Raw Data (Resolution): {mkt.raw_data}")
        print(f"  - YES Bet Status: {b_yes.status} | Realized PnL: ${b_yes.realized_pnl:+.2f}")
        print(f"  - NO Bet Status: {b_no.status} | Realized PnL: ${b_no.realized_pnl:+.2f}")
        print(f"  - Portfolio Cash Balance: ${pf.cash_balance:.2f}")
        print(f"  - Portfolio Total Realized PnL: ${pf.total_realized_pnl:+.2f}")

if __name__ == "__main__":
    run_live_settlement_test()
