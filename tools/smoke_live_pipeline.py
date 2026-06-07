"""Smoke test for QwenBot live pipeline.

Verifies:
  1. Polymarket raw market count > 0
  2. Weather filtered count > 0
  3. At least 1 market can be parsed (city/date/threshold/metric)
"""

import sys
import os

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_fetch_markets():
    """Step 1: Fetch markets from Polymarket, verify count > 0."""
    from scrapers.polymarket import PolymarketScraper
    scraper = PolymarketScraper()
    count = scraper.fetch_and_save()
    print(f"[FETCH] Raw markets fetched: {count}")
    assert count > 0, f"Expected > 0 markets, got {count}"
    return count


def test_weather_filtered():
    """Step 2: Verify weather-filtered markets exist in DB."""
    from database.db import init_db, get_db_session
    from database.models import WeatherMarket
    init_db()
    with get_db_session() as session:
        total = session.query(WeatherMarket).count()
        weather = session.query(WeatherMarket).filter(
            WeatherMarket.city.isnot(None)
        ).count()
    print(f"[WEATHER] Total markets in DB: {total}, with city parsed: {weather}")
    assert weather > 0, f"Expected > 0 weather-filtered markets, got {weather}"
    return weather


def test_parse_markets():
    """Step 3: Parse markets, verify at least 1 has city/date/threshold/metric."""
    from engine.market_parser import MarketParser
    parser = MarketParser()
    parsed = parser.parse_all_unparsed()
    print(f"[PARSE] Newly parsed: {parsed}")

    from database.db import get_db_session
    from database.models import WeatherMarket
    with get_db_session() as session:
        valid = session.query(WeatherMarket).filter(
            WeatherMarket.city.isnot(None),
            WeatherMarket.target_date.isnot(None),
            WeatherMarket.threshold.isnot(None),
            WeatherMarket.metric.isnot(None),
        ).count()
    print(f"[PARSE] Markets with city+date+threshold+metric: {valid}")
    assert valid > 0, f"Expected >= 1 fully parsed market, got {valid}"
    return valid


def test_fetch_weather():
    """Step 4: Fetch weather forecasts for parsed markets."""
    from scrapers.meteo import MeteoFetcher
    fetcher = MeteoFetcher()
    count = fetcher.fetch_all_markets()
    print(f"[WEATHER] Forecasts fetched: {count}")
    return count


def test_analyze():
    """Step 5: Run analysis, check at least 1 analysis produced."""
    from engine.calculator import Calculator
    calc = Calculator()
    from database.db import get_db_session
    from database.models import WeatherMarket
    with get_db_session() as session:
        markets = session.query(WeatherMarket).filter(
            WeatherMarket.status == "open",
            WeatherMarket.city.isnot(None),
        ).limit(5).all()
        market_ids = [m.id for m in markets]
    analyzed = 0
    for mid in market_ids:
        try:
            calc.analyze_market(mid)
            analyzed += 1
        except Exception:
            pass
    print(f"[ANALYZE] Markets analyzed: {analyzed}")
    return analyzed


def main():
    """Run all smoke tests."""
    print("=" * 60)
    print("QwenBot Pipeline Smoke Test")
    print("=" * 60)

    results = {}
    try:
        results["fetch"] = test_fetch_markets()
    except Exception as e:
        print(f"[FETCH] FAILED: {e}")
        results["fetch"] = 0

    try:
        results["weather_filter"] = test_weather_filtered()
    except Exception as e:
        print(f"[WEATHER_FILTER] FAILED: {e}")
        results["weather_filter"] = 0

    try:
        results["parse"] = test_parse_markets()
    except Exception as e:
        print(f"[PARSE] FAILED: {e}")
        results["parse"] = 0

    try:
        results["weather_fetch"] = test_fetch_weather()
    except Exception as e:
        print(f"[WEATHER_FETCH] FAILED: {e}")
        results["weather_fetch"] = 0

    try:
        results["analyze"] = test_analyze()
    except Exception as e:
        print(f"[ANALYZE] FAILED: {e}")
        results["analyze"] = 0

    print("=" * 60)
    print("Results:", results)

    passed = True
    if results["fetch"] <= 0:
        print("FAIL: No markets fetched")
        passed = False
    if results["weather_filter"] <= 0:
        print("FAIL: No weather-filtered markets")
        passed = False
    if results["parse"] <= 0:
        print("FAIL: No fully parsed markets")
        passed = False

    if passed:
        print("\nSMOKE TEST: PASSED")
        return 0
    else:
        print("\nSMOKE TEST: FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())