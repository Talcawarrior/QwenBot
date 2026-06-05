"""Job for fetching weather forecast data from Open-Meteo."""

import logging
from scrapers.meteo import MeteoFetcher

logger = logging.getLogger("JOB_FETCH_WEATHER")


async def run(lat: float, lon: float):
    """Fetch forecast data."""
    fetcher = MeteoFetcher()
    try:
        logger.info("Fetching forecast from Open-Meteo for coordinates: %s, %s", lat, lon)
        forecast = await fetcher.fetch_weather_data(lat, lon)
        return forecast
    finally:
        await fetcher.close_session()
