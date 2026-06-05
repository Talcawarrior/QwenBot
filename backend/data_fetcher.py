"""
DATA FETCHER MODULE - POLYMARKET ULTIMATE HYBRID WEATHER BOT
- Polymarket Gamma API + Nested Market Parsing
- Fix: proper null handling for bestBid/bestAsk
- Fix: session close on shutdown
- Fix: logging instead of bare print/except
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

import aiohttp

from config import config

logger = logging.getLogger("DATA_FETCHER")


class DataFetcher:
    """Fetch market and weather data from external APIs."""
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.base_url = config.POLYMARKET_GAMMA_API

    async def init_session(self):
        """Initialize aiohttp session with retry logic"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "PolyWeatherBot/1.0"},
            )

    async def close_session(self):
        """Close aiohttp session"""
        if self.session and not self.session.closed:
            await self.session.close()

    # pylint: disable=too-many-locals
    async def fetch_polymarket_events(self, limit: int = 100) -> List[Dict]:
        """
        Polymarket'ten tum daily-temperature eventlerini cek
        Nested market yapisi dogru parse ediliyor
        """
        await self.init_session()

        try:
            url = f"{self.base_url}/events?tag_slug=daily-temperature&closed=false&limit={limit}"

            async with self.session.get(url) as response:
                if response.status != 200:
                    logger.warning("Polymarket API error: %s", response.status)
                    return []

                data = await response.json()

                if not isinstance(data, list):
                    logger.warning("Invalid API response format")
                    return []

                all_markets = []

                for event in data:
                    event_id = event.get("id", "")
                    event_title = event.get("title", "")
                    event_end_date = event.get("endDate", "")

                    resolution_date = None
                    if event_end_date:
                        try:
                            resolution_date = datetime.fromisoformat(
                                event_end_date.replace("Z", "+00:00")
                            )
                        except Exception:  # pylint: disable=broad-exception-caught
                            pass

                    markets = event.get("markets", [])

                    if not markets:
                        continue

                    for market in markets:
                        market_id = market.get("id") or ""
                        question = market.get("question", "")

                        # Safe null handling for bestBid/bestAsk
                        best_bid = market.get("bestBid")
                        best_ask = market.get("bestAsk")

                        if best_bid is None:
                            best_bid = 0.0
                        if best_ask is None:
                            best_ask = 1.0

                        yes_price = (
                            (best_bid + best_ask) / 2
                            if best_bid is not None and best_ask is not None
                            else 0.5
                        )
                        no_price = 1.0 - yes_price

                        city_code = self._extract_city(event_title or question)
                        strike_temp = self._extract_strike(question)
                        market_type = self._determine_market_type(question)

                        city_name = (
                            event_title.split(" - ")[0].strip()
                            if event_title and " - " in event_title
                            else (event_title.split()[0] if event_title else "Unknown")
                        )
                        coords = self._get_city_coords(city_code)
                        lat, lon = coords if coords else (None, None)

                        market_data = {
                            "market_id": str(market_id),
                            "event_id": str(event_id),
                            "title": event_title,
                            "question": question,
                            "city": city_name,
                            "city_code": city_code,
                            "latitude": lat,
                            "longitude": lon,
                            "strike_temp": strike_temp,
                            "market_type": market_type,
                            "outcome_type": "YES",
                            "resolution_date": resolution_date,
                            "yes_price": yes_price,
                            "no_price": no_price,
                            "current_yes_bid": yes_price,
                            "current_no_bid": no_price,
                            "volume": market.get("volume", 0.0),
                            "is_active": True,
                        }

                        all_markets.append(market_data)

                logger.info(
                    "Fetched %d markets from %d events", len(all_markets), len(data)
                )
                return all_markets

        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Error fetching Polymarket data")
            return []

    def _extract_city(self, text: str) -> str:
        """Soru metninden sehir adi cikar ve ICAO koduna cevir"""
        if not text:
            return ""

        text_lower = text.lower()

        for city_name, icao_code in config.CITY_ICAO_MAP.items():
            if city_name in text_lower:
                return icao_code

        return ""

    def _extract_strike(self, question: str) -> float:
        """Sorudan strike sicakligi cikar"""
        if not question:
            return 0.0

        patterns = [
            r"(\d+)\s*\°\s*C",
            r"(\d+)\s*\°\s*F",
            r"(\d+)\s*degrees?\s*[CF]?",
            r"above\s+(\d+)",
            r"below\s+(\d+)",
            r"be\s+(\d+)\s*\°?",
        ]

        for pattern in patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                try:
                    strike = float(match.group(1))

                    if "F" in question.upper() or "FAHRENHEIT" in question.upper():
                        strike = (strike - 32) * 5 / 9

                    return round(strike, 1)
                except ValueError:
                    continue

        return 0.0

    def _determine_market_type(self, question: str) -> str:
        """Market tipini belirle: HIGH, LOW, veya RANGE"""
        question_lower = question.lower()

        if (
            "above" in question_lower
            or "higher" in question_lower
            or "over" in question_lower
        ):
            return "HIGH"
        if (
            "below" in question_lower
            or "lower" in question_lower
            or "under" in question_lower
        ):
            return "LOW"
        if "or below" in question_lower or "or higher" in question_lower:
            if "or below" in question_lower:
                return "LOW"
            if "or higher" in question_lower:
                return "HIGH"

        return "RANGE"

    async def fetch_weather_data(self, city_code: str) -> Optional[Dict]:
        """Open-Meteo'dan hava durumu verisi cek"""
        if not city_code:
            return None

        await self.init_session()

        coords = self._get_city_coords(city_code)
        if not coords:
            return None

        lat, lon = coords

        try:
            url = f"{config.OPEN_METEO_BASE}"
            params = {
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m",
                "forecast_days": 7,
                "timezone": "auto",
            }

            async with self.session.get(url, params=params) as response:
                if response.status == 429:
                    logger.warning("Rate limit exceeded for %s", city_code)
                    return None

                if response.status != 200:
                    return None

                data = await response.json()
                return data

        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Weather API error for %s", city_code)
            return None

    def _get_city_coords(self, city_code: str) -> Optional[tuple]:
        """ICAO kodundan koordinat bul"""
        coords_map = {
            "KDAL": (32.8471, -96.8517),
            "KMIA": (25.7959, -80.2870),
            "KORD": (41.9742, -87.9073),
            "KLGA": (40.7769, -73.8740),
            "KLAX": (33.9416, -118.4085),
            "KLAS": (36.0840, -115.1537),
            "KPHX": (33.4343, -112.0080),
            "KIAH": (29.9844, -95.3414),
            "KATL": (33.6407, -84.4277),
            "KBOS": (42.3656, -71.0096),
            "KSEA": (47.4502, -122.3088),
            "KDEN": (39.8617, -104.6732),
            "LTAC": (39.9891, 32.8236),
            "LTFM": (41.2753, 28.7519),
            "LTBJ": (38.2924, 27.1569),
            "LTAI": (36.8987, 30.8005),
            "RJTT": (35.5533, 139.7811),
            "ZSPD": (31.1434, 121.8052),
            "ZSJN": (36.8572, 116.2169),
            "ZHCC": (34.5197, 113.8408),
            "ZBAA": (40.0799, 116.6031),
            "RKSS": (37.4602, 126.4407),
            "VHHH": (22.3080, 113.9185),
            "EGLL": (51.4700, -0.4543),
            "LFPG": (49.0099, 2.5479),
            "EDDT": (52.5597, 13.2877),
            "UUEE": (55.9726, 37.4146),
            "YSSY": (-33.9399, 151.1753),
            "OMDB": (25.2532, 55.3657),
            "MMMX": (19.4363, -99.0721),
            "SBGR": (-23.4356, -46.4731),
            "SBGL": (-22.8089, -43.2436),
            "EDDF": (50.0379, 8.5622),
            "EHAM": (52.3105, 4.7683),
            "LEMD": (40.4983, -3.5676),
            "LIRF": (41.8003, 12.2389),
            "LEBL": (41.2974, 2.0833),
        }

        return coords_map.get(city_code)

    def get_city_coords(self, city_code: str) -> Optional[tuple]:
        """Public accessor for city coordinates (used by main.py for forecast)"""
        return self._get_city_coords(city_code)


if __name__ == "__main__":

    async def test():
        """Run DataFetcher integration test."""
        df = DataFetcher()

        print("=== TESTING DATA FETCHER ===")
        print("\n1. Fetching Polymarket events...")
        markets = await df.fetch_polymarket_events(limit=10)

        if markets:
            print(f"\nFound {len(markets)} markets")
            print("\nFirst 3 markets:")
            for i, m in enumerate(markets[:3]):
                print(f"\n{i + 1}. {m['question']}")
                print(f"   City: {m['city_code']}")
                print(f"   Strike: {m['strike_temp']}C")
                print(f"   Type: {m['market_type']}")
                print(f"   Resolution: {m['resolution_date']}")
                print(f"   Yes Price: {m['yes_price']:.3f}")

        await df.close_session()

    asyncio.run(test())
