"""Piyasa ve meteoroloji lokasyon eşleştirme modülü."""

from typing import Optional
from scrapers.polymarket import PolymarketScraper


class LocationMatcher:
    """Matches markets with coordinates and city information."""

    def __init__(self):
        self.scraper = PolymarketScraper()

    def get_coordinates(self, city_code: str) -> Optional[tuple]:
        """Get lat/lon coordinates from city code."""
        return self.scraper.get_city_coords(city_code)
