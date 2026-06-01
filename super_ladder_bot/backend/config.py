"""
PolyMarkets Super Ladder Bot - Configuration
PAPER TRADING EDITION - Tüm ayarlar burada tanımlı
"""
from dataclasses import dataclass, field
from typing import List, Dict
import os
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Bot konfigürasyonu - tüm limitler ve ayarlar"""
    
    # === PAPER MODE AYARLARI ===
    DRY_RUN: bool = field(default_factory=lambda: os.getenv("DRY_RUN", "true").lower() == "true")
    STARTING_CAPITAL: float = field(default_factory=lambda: float(os.getenv("STARTING_CAPITAL", "1000.0")))
    
    # === RİSK YÖNETİMİ ===
    TOTAL_EXPOSURE_PCT: float = field(default_factory=lambda: float(os.getenv("TOTAL_EXPOSURE_PCT", "0.25")))
    MAX_BET_PCT: float = field(default_factory=lambda: float(os.getenv("MAX_BET_PCT", "0.03")))
    EDGE_THRESHOLD: float = field(default_factory=lambda: float(os.getenv("EDGE_THRESHOLD", "0.03")))
    KELLY_FRACTION: float = field(default_factory=lambda: float(os.getenv("KELLY_FRACTION", "0.15")))
    DAILY_LOSS_LIMIT: float = field(default_factory=lambda: float(os.getenv("DAILY_LOSS_LIMIT", "0.05")))
    MAX_BETS_PER_CITY: int = field(default_factory=lambda: int(os.getenv("MAX_BETS_PER_CITY", "4")))
    MAX_REGIONAL_EXPOSURE_PCT: float = 0.10  # Bölge başına max %10
    
    # === TARAMA AYARLARI ===
    SCAN_INTERVAL: int = field(default_factory=lambda: int(os.getenv("SCAN_INTERVAL", "240")))
    LADDER_LEVELS: int = 4
    LADDER_WEIGHTS: List[float] = field(default_factory=lambda: [0.15, 0.25, 0.35, 0.25])
    PRICE_STEP: float = 0.01
    
    # === API ENDPOINT'LERİ ===
    POLYMARKET_GAMMA_API: str = "https://gamma-api.polymarket.com"
    OPENMETEO_BASE: str = "https://api.open-meteo.com/v1"
    
    # === HAVA DURUMU MODELLERİ ===
    OPENMETEO_ENDPOINTS: Dict[str, str] = field(default_factory=lambda: {
        "gfs": "https://api.open-meteo.com/v1/gfs",
        "ecmwf": "https://api.open-meteo.com/v1/ecmwf",
        "cma": "https://api.open-meteo.com/v1/cma",
        "jma": "https://api.open-meteo.com/v1/jma",
        "kma": "https://api.open-meteo.com/v1/kma",
        "dwd_icon": "https://api.open-meteo.com/v1/dwd-icon",
        "meteofrance": "https://api.open-meteo.com/v1/meteofrance",
        "ukmo": "https://api.open-meteo.com/v1/ukmo"
    })
    
    # === ŞEHİR LİSTESİ (TÜM POLYMARKET ŞEHİRLERİ) ===
    CITIES: List[Dict[str, any]] = field(default_factory=lambda: [
        {"name": "NYC", "lat": 40.7128, "lon": -74.0060, "region": "Northeast"},
        {"name": "Dallas", "lat": 32.7767, "lon": -96.7970, "region": "South"},
        {"name": "Chicago", "lat": 41.8781, "lon": -87.6298, "region": "Midwest"},
        {"name": "Los Angeles", "lat": 34.0522, "lon": -118.2437, "region": "West"},
        {"name": "Boston", "lat": 42.3601, "lon": -71.0589, "region": "Northeast"},
        {"name": "Denver", "lat": 39.7392, "lon": -104.9903, "region": "West"},
        {"name": "Atlanta", "lat": 33.7490, "lon": -84.3880, "region": "South"},
        {"name": "Miami", "lat": 25.7617, "lon": -80.1918, "region": "South"},
        {"name": "Phoenix", "lat": 33.4484, "lon": -112.0740, "region": "West"},
        {"name": "Seattle", "lat": 47.6062, "lon": -122.3321, "region": "West"},
        {"name": "Houston", "lat": 29.7604, "lon": -95.3698, "region": "South"},
        {"name": "Minneapolis", "lat": 44.9778, "lon": -93.2650, "region": "Midwest"},
        {"name": "Washington DC", "lat": 38.9072, "lon": -77.0369, "region": "Northeast"},
        {"name": "San Francisco", "lat": 37.7749, "lon": -122.4194, "region": "West"},
        {"name": "Detroit", "lat": 42.3314, "lon": -83.0458, "region": "Midwest"},
        {"name": "Salt Lake City", "lat": 40.7608, "lon": -111.8910, "region": "West"},
        {"name": "Tampa", "lat": 27.9506, "lon": -82.4572, "region": "South"},
        {"name": "Orlando", "lat": 28.5383, "lon": -81.3792, "region": "South"},
        {"name": "Philadelphia", "lat": 39.9526, "lon": -75.1652, "region": "Northeast"},
        {"name": "Las Vegas", "lat": 36.1699, "lon": -115.1398, "region": "West"},
        {"name": "Portland", "lat": 45.5152, "lon": -122.6784, "region": "West"},
        {"name": "Charlotte", "lat": 35.2271, "lon": -80.8431, "region": "South"},
        {"name": "Nashville", "lat": 36.1627, "lon": -86.7816, "region": "South"},
        {"name": "Baltimore", "lat": 39.2904, "lon": -76.6122, "region": "Northeast"},
        {"name": "Milwaukee", "lat": 43.0389, "lon": -87.9065, "region": "Midwest"},
        {"name": "Kansas City", "lat": 39.0997, "lon": -94.5786, "region": "Midwest"},
        {"name": "Cleveland", "lat": 41.4993, "lon": -81.6944, "region": "Midwest"},
        {"name": "New Orleans", "lat": 29.9511, "lon": -90.0715, "region": "South"},
        {"name": "Raleigh", "lat": 35.7796, "lon": -78.6382, "region": "South"},
    ])
    
    # === DATABASE ===
    DATABASE_PATH: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "data/bot.db"))
    LOG_PATH: str = field(default_factory=lambda: os.getenv("LOG_PATH", "logs/bot.log"))
    
    # === WEBSOCKET ===
    WS_HOST: str = "0.0.0.0"
    WS_PORT: int = 8765
    
    # === FASTAPI ===
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    
    @property
    def is_paper_mode(self) -> bool:
        """Paper mode kontrolü"""
        return self.DRY_RUN
    
    @property
    def max_exposure_amount(self) -> float:
        """Toplam max exposure tutarı"""
        return self.STARTING_CAPITAL * self.TOTAL_EXPOSURE_PCT
    
    @property
    def max_bet_amount(self) -> float:
        """Tek bet max tutarı"""
        return self.STARTING_CAPITAL * self.MAX_BET_PCT
    
    @property
    def daily_loss_amount(self) -> float:
        """Günlük stop-loss tutarı"""
        return self.STARTING_CAPITAL * self.DAILY_LOSS_LIMIT
    
    def get_city_by_name(self, name: str) -> Dict:
        """Şehir bilgisi getir"""
        for city in self.CITIES:
            if city["name"].lower() == name.lower():
                return city
        return None
    
    def get_cities_by_region(self, region: str) -> List[Dict]:
        """Bölgeye göre şehirleri getir"""
        return [city for city in self.CITIES if city.get("region") == region]


# Global config instance
config = Config()
