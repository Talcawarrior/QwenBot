"""Verify the bot placed bets on BOTH highest and lowest temperature markets,
across multiple cities, on dates within today + 2 days."""

import sys
from datetime import datetime, timezone, timedelta
from collections import Counter

sys.path.insert(0, ".")

from database.db import get_db_session
from database.models import Bet, WeatherMarket, Analysis


def main():
    with get_db_session() as session:
        bets = session.query(Bet).all()
        markets = session.query(WeatherMarket).all()
        analyses = session.query(Analysis).all()

        print("=== DB Summary ===")
        print(f"Markets:        {len(markets)}")
        print(f"Analyses:       {len(analyses)}")
        print(f"Bets (all):     {len(bets)}")
        print()

        # Per-city, per-metric breakdown
        market_by_id = {m.id: m for m in markets}
        by_city_metric = Counter()
        for bet in bets:
            m = market_by_id.get(bet.market_id)
            if not m:
                continue
            by_city_metric[(m.city, m.metric)] += 1

        print("=== Bets by (city, metric) ===")
        for (city, metric), n in sorted(by_city_metric.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {city:>12}  {metric:<18}  {n}")
        print()

        # Coverage checks
        metrics = {m.metric for m in markets}
        cities = {m.city for m in markets}
        print("=== Coverage ===")
        print(f"Distinct metrics:  {metrics}")
        print(f"Distinct cities:   {len(cities)}  {sorted(cities)}")
        print()

        # Date range check
        now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        max_date = now + timedelta(days=2, hours=23, minutes=59)
        out_of_scope = []
        for m in markets:
            if m.target_date is None:
                continue
            target = m.target_date
            if target.tzinfo is None:
                target = target.replace(tzinfo=timezone.utc)
            if target < now or target > max_date:
                out_of_scope.append((m.id, m.city, m.target_date))
        print("=== Date Scope ===")
        print(f"Markets out of scope (not today..today+2d): {len(out_of_scope)}")
        for mid, c, t in out_of_scope[:5]:
            print(f"  {c:>12}  {t}")
        if len(out_of_scope) > 5:
            print(f"  ... and {len(out_of_scope) - 5} more")
        print()

        # High vs low temperature balance
        n_max = sum(1 for m in markets if m.metric == "temperature_max")
        n_min = sum(1 for m in markets if m.metric == "temperature_min")
        bets_max = sum(1 for b in bets if market_by_id.get(b.market_id) and market_by_id[b.market_id].metric == "temperature_max")
        bets_min = sum(1 for b in bets if market_by_id.get(b.market_id) and market_by_id[b.market_id].metric == "temperature_min")
        print("=== High vs Low ===")
        print(f"Markets temperature_max: {n_max}, bets: {bets_max}")
        print(f"Markets temperature_min: {n_min}, bets: {bets_min}")


if __name__ == "__main__":
    main()
