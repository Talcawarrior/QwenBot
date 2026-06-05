"""Piyasa sorusunu çözümleyen parser modülü (Regex & Kural tabanlı)."""

import re
import logging
from datetime import datetime
from config.settings import config
from database.db import get_session
from database.models import WeatherMarket

logger = logging.getLogger("ENGINE_MARKET_PARSER")


class MarketParser:
    """Parses text questions to extract structural fields."""

    CITY_ALIASES = {
        "nyc": "new york",
        "new york city": "new york",
        "la": "los angeles",
        "sf": "san francisco",
        "dc": "washington",
        "phx": "phoenix",
        "dallas": "dallas",
        "istanbul": "istanbul",
        "london": "london",
        "jinan": "jinan",
        "zhengzhou": "zhengzhou",
        "tokyo": "tokyo",
        "ankara": "ankara",
        "antalya": "antalya",
        "izmir": "izmir",
    }

    def _extract_city(self, question: str) -> str | None:
        q = question.lower()
        all_cities = list(self.CITY_ALIASES.values()) + list(self.CITY_ALIASES.keys())
        for city in sorted(all_cities, key=len, reverse=True):
            if city in q:
                return self.CITY_ALIASES.get(city, city)
        return None

    def _extract_threshold(self, question: str) -> tuple[float, str] | None:
        """Sıcaklık eşiğini bul."""
        patterns = [
            r'(\d+\.?\d*)\s*°?\s*[Ff](?:ahrenheit)?',
            r'(\d+\.?\d*)\s*°?\s*[Cc](?:elsius)?',
            r'exceed\s+(\d+\.?\d*)',
            r'above\s+(\d+\.?\d*)',
            r'below\s+(\d+\.?\d*)',
            r'over\s+(\d+\.?\d*)',
            r'under\s+(\d+\.?\d*)',
            r'be\s+(\d+\.?\d*)'
        ]

        for pattern in patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                try:
                    value = float(match.group(1))
                    unit = "fahrenheit" if "f" in pattern.lower() or "f" in question.lower() else "celsius"

                    # Convert Fahrenheit to Celsius
                    if unit == "fahrenheit" or value > 60:
                        value_c = (value - 32) * 5 / 9
                        return round(value_c, 1), "celsius"
                    return round(value, 1), "celsius"
                except ValueError:
                    continue
        return None

    def _extract_date(self, question: str) -> datetime | None:
        """Tarih bul."""
        patterns = [
            r'(\w+ \d{1,2},?\s*\d{4})',        # July 4, 2025
            r'(\d{4}-\d{2}-\d{2})',            # 2025-07-04
            r'(\d{1,2}/\d{1,2}/\d{4})',        # 7/4/2025
            r'on\s+(\w+\s+\d{1,2})',           # on May 20
        ]

        for pattern in patterns:
            match = re.search(pattern, question)
            if match:
                date_str = match.group(1)
                # Handle simplified date format e.g. "May 20" by assuming current year (2026)
                if "on " in pattern:
                    date_str = f"{date_str} 2026"
                for fmt in ["%B %d, %Y", "%B %d %Y", "%Y-%m-%d", "%m/%d/%Y", "%B %d %Y"]:
                    try:
                        return datetime.strptime(date_str.strip(), fmt)
                    except ValueError:
                        continue
        return None

    def _extract_metric(self, question: str) -> str:
        """Ne ölçülüyor?"""
        q = question.lower()

        if any(w in q for w in ["high temp", "max temp", "exceed", "above", "over", "hot", "highest"]):
            return "temperature_max"
        if any(w in q for w in ["low temp", "min temp", "below", "under", "cold", "lowest"]):
            return "temperature_min"
        if any(w in q for w in ["rain", "precipitation", "rainfall"]):
            return "precipitation_mm"
        if any(w in q for w in ["snow", "snowfall"]):
            return "snow_cm"
        if any(w in q for w in ["wind", "gust"]):
            return "wind_speed_kmh"

        return "temperature_max"  # Default

    def parse_and_update(self, market_id: str) -> bool:
        """Bir marketi parse et ve DB'yi güncelle."""
        with get_session() as session:
            market = session.query(WeatherMarket).filter_by(id=market_id).first()
            if not market:
                return False

            question = market.question

            city = self._extract_city(question)
            threshold_result = self._extract_threshold(question)
            target_date = self._extract_date(question)
            metric = self._extract_metric(question)

            if city:
                market.city = city
                # Map city code (for ICAO compatibility)
                from scrapers.polymarket import PolymarketScraper
                for k, v in config.CITY_ICAO_MAP.items():
                    if k in city.lower():
                        market.city_code = v
                        coords = PolymarketScraper().get_city_coords(v)
                        if coords:
                            market.latitude, market.longitude = coords
                        break

            if threshold_result:
                market.threshold, market.threshold_unit = threshold_result
            if target_date:
                market.target_date = target_date
            market.metric = metric

            parsed = bool(city and threshold_result and target_date)

            if not parsed:
                logger.warning(
                    f"Market {market_id} tam parse edilemedi: "
                    f"city={city}, threshold={threshold_result}, date={target_date}"
                )

            return parsed

    def parse_all_unparsed(self) -> int:
        """Parse edilmemiş tüm marketleri parse et."""
        count = 0
        with get_session() as session:
            unparsed = session.query(WeatherMarket).filter(
                WeatherMarket.city.is_(None) |
                WeatherMarket.target_date.is_(None)
            ).all()
            market_ids = [m.id for m in unparsed]

        for mid in market_ids:
            try:
                if self.parse_and_update(mid):
                    count += 1
            except Exception as e:
                logger.error(f"Parse hatası {mid}: {e}")
                continue

        return count
