"""Meteo weather forecast scraper module."""

import logging
from typing import Dict, Optional
import aiohttp
from config.settings import config

logger = logging.getLogger("SCRAPER_METEO")


class MeteoFetcher:
    """Fetches real-time weather forecasts from Open-Meteo."""

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def init_session(self):
        """Initialize session."""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "PolyWeatherBot/1.0"},
            )

    async def close_session(self):
        """Close session."""
        if self.session and not self.session.closed:
            await self.session.close()

    async def fetch_weather_data(self, lat: float, lon: float) -> Optional[Dict]:
        """Fetch forecasts from Open-Meteo API."""
        await self.init_session()
        try:
            url = config.OPEN_METEO_BASE
            params = {
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "forecast_days": 7,
                "timezone": "auto",
            }
            async with self.session.get(url, params=params) as response:
                if response.status == 429:
                    logger.warning("Rate limit exceeded")
                    return None
                if response.status != 200:
                    return None
                return await response.json()
        except Exception:
            logger.exception("Weather API error")
            return None
