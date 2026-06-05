"""Polymarket scraper module fetching and filtering weather events."""

import json
import logging
import requests
import re
from datetime import datetime
from typing import Optional
from database.db import get_session
from database.models import WeatherMarket
from config.settings import config, bot_config
from utils.retry import retry
from utils.errors import ScraperError

logger = logging.getLogger("SCRAPER_POLYMARKET")


class PolymarketScraper:
    """Scrapes weather prediction markets from Polymarket Gamma API."""

    def __init__(self):
        self.gamma_url = bot_config.polymarket.gamma_url
        self.keywords = bot_config.polymarket.weather_keywords

    async def init_session(self):
        """Mock init session for test compatibility."""
        pass

    async def close_session(self):
        """Mock close session for test compatibility."""
        pass

    @retry(max_attempts=3, delay=5, exceptions=(requests.RequestException,))
    def _fetch_raw_markets(self) -> list[dict]:
        """Polymarket'ten ham veri çek."""
        all_markets = []
        offset = 0
        limit = 100

        while offset < 2000:
            resp = requests.get(
                f"{self.gamma_url}/markets",
                params={
                    "closed": False,
                    "limit": limit,
                    "offset": offset,
                    "active": True,
                },
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()

            if not data:
                break

            all_markets.extend(data)
            offset += limit

            if len(data) < limit:
                break

        logger.info(f"Toplam {len(all_markets)} market çekildi")
        return all_markets

    async def fetch_polymarket_events(self, limit: int = 100) -> list[dict]:
        """Fetch daily-temperature events for compatibility with test suite."""
        raw_markets = self._fetch_raw_markets()
        formatted = []
        for raw in raw_markets[:limit]:
            formatted.append(self._parse_market(raw))
        return formatted

    def _is_weather_market(self, market: dict) -> bool:
        """Bu market hava durumu ile ilgili mi?"""
        question = (market.get("question", "") + " " + market.get("description", "")).lower()
        return any(kw.lower() in question for kw in self.keywords)

    def _parse_market(self, raw: dict) -> dict:
        """Ham marketi yapılandırılmış veriye çevir."""
        tokens = raw.get("tokens", [])
        yes_price = None
        no_price = None

        for token in tokens:
            if token.get("outcome", "").upper() == "YES":
                yes_price = float(token.get("price", 0))
            elif token.get("outcome", "").upper() == "NO":
                no_price = float(token.get("price", 0))

        if yes_price is None:
            yes_price = 0.5
        if no_price is None:
            no_price = 0.5

        # Extract city name dynamically from ICAO map keys
        city_name = "Unknown"
        title_lower = (raw.get("title") or "").lower()
        question_lower = (raw.get("question") or "").lower()
        for k in config.CITY_ICAO_MAP.keys():
            if k in title_lower or k in question_lower:
                city_name = k.title()
                break

        if city_name == "Unknown":
            event_title = raw.get("title") or ""
            city_name = (
                event_title.split(" - ")[0].strip()
                if event_title and " - " in event_title
                else (event_title.split()[0] if event_title else "Unknown")
            )

        # Ensure correct numeric market ID matching the betting and settlement engines
        market_id_val = str(raw.get("id"))

        return {
            "id": market_id_val,
            "condition_id": raw.get("condition_id"),
            "question": raw.get("question", ""),
            "yes_price": yes_price,
            "no_price": no_price,
            "volume": float(raw.get("volume", 0) or 0),
            "liquidity": float(raw.get("liquidity", 0) or 0),
            "end_date": raw.get("end_date_iso"),
            "raw_data": json.dumps(raw),
            "city_name": city_name,
            "city": city_name
        }

    def fetch_and_save(self) -> int:
        """Ana fonksiyon: Çek -> Filtrele -> Kaydet."""
        try:
            raw_markets = self._fetch_raw_markets()
        except Exception as e:
            raise ScraperError(f"Polymarket API hatası: {e}")

        weather_markets = [m for m in raw_markets if self._is_weather_market(m)]
        logger.info(f"{len(weather_markets)} hava durumu marketi bulundu")

        saved = 0
        with get_session() as session:
            for raw in weather_markets:
                try:
                    parsed = self._parse_market(raw)

                    # Upsert
                    existing = session.query(WeatherMarket).filter_by(
                        id=parsed["id"]
                    ).first()

                    if existing:
                        existing.yes_price = parsed["yes_price"]
                        existing.no_price = parsed["no_price"]
                        existing.volume = parsed["volume"]
                        existing.liquidity = parsed["liquidity"]
                        existing.city = parsed["city"]
                        existing.last_updated = datetime.utcnow()
                        existing.raw_data = parsed["raw_data"]
                    else:
                        market = WeatherMarket(
                            id=parsed["id"],
                            question=parsed["question"],
                            yes_price=parsed["yes_price"],
                            no_price=parsed["no_price"],
                            volume=parsed["volume"],
                            liquidity=parsed["liquidity"],
                            city=parsed["city"],
                            first_seen=datetime.utcnow(),
                            last_updated=datetime.utcnow(),
                            raw_data=parsed["raw_data"],
                            status="open"
                        )
                        session.add(market)
                    saved += 1

                except Exception as e:
                    logger.error(f"Market parse hatası {raw.get('id')}: {e}")
                    continue

            logger.info(f"{saved} market kaydedildi/güncellendi")
        return saved

    def get_city_coords(self, city_code: str) -> Optional[tuple]:
        """ICAO kodundan koordinat bul."""
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

    def _extract_city(self, text: str) -> str:
        if not text:
            return ""
        text_lower = text.lower()
        for city_name, icao_code in config.CITY_ICAO_MAP.items():
            if city_name in text_lower:
                return icao_code
        return ""

    def _extract_strike(self, question: str) -> float:
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
