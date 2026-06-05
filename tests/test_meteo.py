"""Test cases for MeteoFetcher."""

import pytest
from scrapers.meteo import MeteoFetcher


@pytest.mark.asyncio
async def test_meteo_fetch():
    fetcher = MeteoFetcher()
    assert hasattr(fetcher, "fetch_weather_data")
