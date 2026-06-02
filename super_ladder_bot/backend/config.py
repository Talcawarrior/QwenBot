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
    
    # === ŞEHİR LİSTESİ (TÜM POLYMARKET ŞEHİRLERİ - 51+ ŞEHİR) ===
    CITIES: List[Dict[str, any]] = field(default_factory=lambda: [
        # ABD Şehirleri (29 şehir)
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
        # Uluslararası Şehirler (Polymarket'ten canlı çekilen)
        {"name": "London", "lat": 51.5074, "lon": -0.1278, "region": "Europe"},
        {"name": "Paris", "lat": 48.8566, "lon": 2.3522, "region": "Europe"},
        {"name": "Berlin", "lat": 52.5200, "lon": 13.4050, "region": "Europe"},
        {"name": "Madrid", "lat": 40.4168, "lon": -3.7038, "region": "Europe"},
        {"name": "Rome", "lat": 41.9028, "lon": 12.4964, "region": "Europe"},
        {"name": "Amsterdam", "lat": 52.3676, "lon": 4.9041, "region": "Europe"},
        {"name": "Moscow", "lat": 55.7558, "lon": 37.6173, "region": "Europe"},
        {"name": "Tokyo", "lat": 35.6762, "lon": 139.6503, "region": "Asia"},
        {"name": "Beijing", "lat": 39.9042, "lon": 116.4074, "region": "Asia"},
        {"name": "Shanghai", "lat": 31.2304, "lon": 121.4737, "region": "Asia"},
        {"name": "Seoul", "lat": 37.5665, "lon": 126.9780, "region": "Asia"},
        {"name": "Singapore", "lat": 1.3521, "lon": 103.8198, "region": "Asia"},
        {"name": "Hong Kong", "lat": 22.3193, "lon": 114.1694, "region": "Asia"},
        {"name": "Mumbai", "lat": 19.0760, "lon": 72.8777, "region": "Asia"},
        {"name": "Delhi", "lat": 28.7041, "lon": 77.1025, "region": "Asia"},
        {"name": "Sydney", "lat": -33.8688, "lon": 151.2093, "region": "Oceania"},
        {"name": "Melbourne", "lat": -37.8136, "lon": 144.9631, "region": "Oceania"},
        {"name": "Toronto", "lat": 43.6532, "lon": -79.3832, "region": "North America"},
        {"name": "Vancouver", "lat": 49.2827, "lon": -123.1207, "region": "North America"},
        {"name": "Mexico City", "lat": 19.4326, "lon": -99.1332, "region": "North America"},
        {"name": "Sao Paulo", "lat": -23.5505, "lon": -46.6333, "region": "South America"},
        {"name": "Buenos Aires", "lat": -34.6037, "lon": -58.3816, "region": "South America"},
        {"name": "Dubai", "lat": 25.2048, "lon": 55.2708, "region": "Middle East"},
        {"name": "Istanbul", "lat": 41.0082, "lon": 28.9784, "region": "Europe"},
        {"name": "Cairo", "lat": 30.0444, "lon": 31.2357, "region": "Africa"},
        {"name": "Lagos", "lat": 6.5244, "lon": 3.3792, "region": "Africa"},
        {"name": "Nairobi", "lat": -1.2921, "lon": 36.8219, "region": "Africa"},
        {"name": "Bangkok", "lat": 13.7563, "lon": 100.5018, "region": "Asia"},
        {"name": "Jakarta", "lat": -6.2088, "lon": 106.8456, "region": "Asia"},
        {"name": "Manila", "lat": 14.5995, "lon": 120.9842, "region": "Asia"},
        {"name": "Ho Chi Minh City", "lat": 10.8231, "lon": 106.6297, "region": "Asia"},
        {"name": "Tel Aviv", "lat": 32.0853, "lon": 34.7818, "region": "Middle East"},
        {"name": "Riyadh", "lat": 24.7136, "lon": 46.6753, "region": "Middle East"},
        {"name": "Jinan", "lat": 36.6512, "lon": 117.1209, "region": "Asia"},
        {"name": "Guangzhou", "lat": 23.1291, "lon": 113.2644, "region": "Asia"},
        {"name": "Chengdu", "lat": 30.5728, "lon": 104.0668, "region": "Asia"},
        {"name": "Chongqing", "lat": 29.4316, "lon": 106.9123, "region": "Asia"},
        {"name": "Wuhan", "lat": 30.5928, "lon": 114.3055, "region": "Asia"},
        {"name": "Zhengzhou", "lat": 34.7466, "lon": 113.6253, "region": "Asia"},
        {"name": "Qingdao", "lat": 36.0671, "lon": 120.3826, "region": "Asia"},
        {"name": "Busan", "lat": 35.1796, "lon": 129.0756, "region": "Asia"},
        {"name": "Taipei", "lat": 25.0330, "lon": 121.5654, "region": "Asia"},
        {"name": "Kuala Lumpur", "lat": 3.1390, "lon": 101.6869, "region": "Asia"},
        {"name": "Panama City", "lat": 8.9824, "lon": -79.5199, "region": "North America"},
        {"name": "Wellington", "lat": -41.2865, "lon": 174.7762, "region": "Oceania"},
        {"name": "Helsinki", "lat": 60.1699, "lon": 24.9384, "region": "Europe"},
        {"name": "Warsaw", "lat": 52.2297, "lon": 21.0122, "region": "Europe"},
        {"name": "Milan", "lat": 45.4642, "lon": 9.1900, "region": "Europe"},
        {"name": "Munich", "lat": 48.1351, "lon": 11.5820, "region": "Europe"},
        {"name": "Cape Town", "lat": -33.9249, "lon": 18.4241, "region": "Africa"},
        {"name": "Ankara", "lat": 39.9334, "lon": 32.8597, "region": "Europe"},
        {"name": "Jeddah", "lat": 21.5433, "lon": 39.1728, "region": "Middle East"},
        {"name": "Karachi", "lat": 24.8607, "lon": 67.0011, "region": "Asia"},
        {"name": "Lucknow", "lat": 26.8467, "lon": 80.9462, "region": "Asia"},
        {"name": "Austin", "lat": 30.2672, "lon": -97.7431, "region": "South"},
        {"name": "San Diego", "lat": 32.7157, "lon": -117.1611, "region": "West"},
        {"name": "San Jose", "lat": 37.3382, "lon": -121.8863, "region": "West"},
        {"name": "Jacksonville", "lat": 30.3322, "lon": -81.6557, "region": "South"},
        {"name": "Fort Worth", "lat": 32.7555, "lon": -97.3308, "region": "South"},
        {"name": "Columbus", "lat": 39.9612, "lon": -82.9988, "region": "Midwest"},
        {"name": "Indianapolis", "lat": 39.7684, "lon": -86.1581, "region": "Midwest"},
        {"name": "San Antonio", "lat": 29.4241, "lon": -98.4936, "region": "South"},
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
