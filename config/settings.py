"""PolyMarket Ultimate Hybrid Weather Bot - Configuration Dataclasses & Legacy Config."""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Compute repo root (parent of config/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load .env from repo root
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _resolve_path(path_value: str, default_relative: str) -> str:
    """Resolve relative paths to absolute from repo root."""
    raw = path_value or default_relative
    if os.path.isabs(raw):
        return raw
    return os.path.join(BASE_DIR, raw)


@dataclass
class PolymarketConfig:
    """Polymarket specific configurations."""
    api_url: str = "https://clob.polymarket.com"
    gamma_url: str = "https://gamma-api.polymarket.com"
    private_key: str = os.getenv("POLY_PRIVATE_KEY", "")
    api_key: str = os.getenv("POLY_API_KEY", "")
    api_secret: str = os.getenv("POLY_API_SECRET", "")
    api_passphrase: str = os.getenv("POLY_API_PASSPHRASE", "")
    weather_keywords: list = None

    def __post_init__(self):
        self.weather_keywords = [
            "temperature", "heat", "cold", "snow", "rain",
            "hurricane", "storm", "weather", "°F", "°C",
            "celsius", "fahrenheit", "precipitation", "highest"
        ]


@dataclass
class MeteoConfig:
    """Weather service API configurations."""
    openmeteo_url: str = "https://api.open-meteo.com/v1/forecast"
    weatherapi_key: str = os.getenv("WEATHERAPI_KEY", "")
    weatherapi_url: str = "https://api.weatherapi.com/v1"


@dataclass
class StrategyConfig:
    """Strategy & bankroll metrics."""
    min_edge: float = 0.03          # Minimum edge (aligned with QwenBot 3%)
    max_bet_amount: float = 50.0    # Maximum $50 per bet
    min_liquidity: float = 1000.0   # Minimum $1000 liquidity
    kelly_fraction: float = 0.15    # Quarter/Fractional Kelly (aligned with QwenBot 15%)
    min_sources: int = 1            # En az 1 hava kaynağı (aligned for Open-Meteo free tier)
    max_days_ahead: int = 14        # 14 günden fazla ileriyi oynama


@dataclass
class BotConfig:
    """Combined configurations."""
    polymarket: PolymarketConfig = None
    meteo: MeteoConfig = None
    strategy: StrategyConfig = None

    def __post_init__(self):
        self.polymarket = self.polymarket or PolymarketConfig()
        self.meteo = self.meteo or MeteoConfig()
        self.strategy = self.strategy or StrategyConfig()


# Main configuration class (kept for backward compatibility with older components & tests)
class Config:
    """Central configuration for the PolyMarket Weather Bot."""

    INITIAL_PORTFOLIO = float(os.getenv("INITIAL_PORTFOLIO", "1000.0"))
    SMART_POOL_PCT = float(os.getenv("SMART_POOL_PCT", "0.40"))
    MAX_EXPOSURE_PCT = float(os.getenv("MAX_EXPOSURE_PCT", "0.25"))
    MAX_BET_PCT = float(os.getenv("MAX_BET_PCT", "0.03"))
    MIN_BET_SIZE = float(os.getenv("MIN_BET_SIZE", "1.0"))
    KELLY_FRACTION = float(os.getenv("KELLY_FRACTION", "0.15"))
    DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", "0.05"))
    CITY_CAP = int(os.getenv("CITY_CAP", "4"))
    SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "300"))
    SETTLEMENT_INTERVAL = int(os.getenv("SETTLEMENT_INTERVAL", "120"))
    SIA_INTERVAL = int(os.getenv("SIA_INTERVAL", "86400"))
    POLYMARKET_GAMMA_API = "https://gamma-api.polymarket.com"
    POLYMARKET_CLOB_API = "https://clob.polymarket.com"
    OPEN_METEO_API = "https://api.open-meteo.com/v1"
    
    MODEL_WEIGHTS = {
        "gfs_seamless": 0.30,
        "ecmwf_ifs04": 0.25,
        "gem_seamless": 0.15,
        "icon_seamless": 0.10,
        "jma_msm": 0.08,
        "cma_grapes_global": 0.05,
        "ukmo_seamless": 0.04,
        "meteofrance_seamless": 0.03,
    }
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = _resolve_path(os.getenv("LOG_FILE"), "logs/bot.log")
    LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s"
    DB_PATH = _resolve_path(os.getenv("DB_PATH"), "data/bot.db")
    DB_ECHO = os.getenv("DB_ECHO", "false").lower() == "true"
    TEMP_UNIT = "celsius"
    DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8091"))

    CITY_ICAO_MAP = {
        "ankara": "LTAC",
        "istanbul": "LTFM",
        "izmir": "LTBJ",
        "antalya": "LTAI",
        "dallas": "KDAL",
        "miami": "KMIA",
        "chicago": "KORD",
        "new york": "KLGA",
        "newyork": "KLGA",
        "los angeles": "KLAX",
        "las vegas": "KLAS",
        "phoenix": "KPHX",
        "houston": "KIAH",
        "atlanta": "KATL",
        "boston": "KBOS",
        "seattle": "KSEA",
        "denver": "KDEN",
        "tokyo": "RJTT",
        "shanghai": "ZSPD",
        "jinan": "ZSJN",
        "zhengzhou": "ZHCC",
        "beijing": "ZBAA",
        "seoul": "RKSS",
        "hong kong": "VHHH",
        "london": "EGLL",
        "paris": "LFPG",
        "berlin": "EDDT",
        "moscow": "UUEE",
        "sydney": "YSSY",
        "dubai": "OMDB",
        "mexico city": "MMMX",
        "sao paulo": "SBGR",
        "rio de janeiro": "SBGL",
        "frankfurt": "EDDF",
        "amsterdam": "EHAM",
        "madrid": "LEMD",
        "rome": "LIRF",
        "barcelona": "LEBL",
    }
    OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"
    FEE_DRAG = 0.005
    MIN_EDGE = 0.03
    TOTAL_EXPOSURE_PCT = 0.25

    @property
    def daily_loss_limit_amount(self):
        """Return absolute daily loss limit amount."""
        return self.INITIAL_PORTFOLIO * self.DAILY_LOSS_LIMIT

    @classmethod
    def get_model_weight(cls, model_name: str) -> float:
        """Return weight for a specific model."""
        return cls.MODEL_WEIGHTS.get(model_name, 0.0)

    @classmethod
    def get_normalized_weights(cls) -> dict:
        """Return normalized model weight dictionary."""
        return cls.MODEL_WEIGHTS

    @classmethod
    def get_smart_pool_amount(cls, portfolio_value: float) -> float:
        """Return smart pool allocation amount."""
        return portfolio_value * cls.SMART_POOL_PCT

    @classmethod
    def get_max_bet_amount(cls, portfolio_value: float) -> float:
        """Return maximum allowed bet amount."""
        return min(portfolio_value * cls.MAX_BET_PCT, portfolio_value * 0.03)

    @classmethod
    def get_max_exposure_amount(cls, portfolio_value: float) -> float:
        """Return maximum allowed total exposure."""
        return portfolio_value * cls.MAX_EXPOSURE_PCT

    @classmethod
    def get_daily_loss_limit(cls, portfolio_value: float) -> float:
        """Return daily loss limit amount."""
        return portfolio_value * cls.DAILY_LOSS_LIMIT


# Singleton instances
config = Config()
bot_config = BotConfig()
