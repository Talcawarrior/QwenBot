"""PolyMarket Ultimate Hybrid Weather Bot - Configuration"""

import os
from dotenv import load_dotenv

# Compute repo root (parent of backend/)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load .env from repo root (not cwd dependent)
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _resolve_path(path_value: str, default_relative: str) -> str:
    """Resolve relative paths to absolute from repo root."""
    raw = path_value or default_relative
    if os.path.isabs(raw):
        return raw
    return os.path.join(BASE_DIR, raw)


_model_weights = {
    "gfs_seamless": 0.30,
    "ecmwf_ifs04": 0.25,
    "gem_seamless": 0.15,
    "icon_seamless": 0.10,
    "jma_msm": 0.08,
    "cma_grapes_global": 0.05,
    "ukmo_seamless": 0.04,
    "meteofrance_seamless": 0.03,
}
_total_weight = sum(_model_weights.values())
if abs(_total_weight - 1.0) > 0.001:
    _model_weights = {k: v / _total_weight for k, v in _model_weights.items()}


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
    MODEL_WEIGHTS = _model_weights
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = _resolve_path(os.getenv("LOG_FILE"), "logs/bot.log")
    LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s"
    DB_PATH = _resolve_path(os.getenv("DB_PATH"), "data/bot.db")
    DB_ECHO = os.getenv("DB_ECHO", "false").lower() == "true"
    TEMP_UNIT = "celsius"
    DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

    # HOST and PORT for uvicorn
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8091"))

    # Missing attributes from bug reports - added for compatibility
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

    # Dinamik hesaplanmalı (INITIAL * DAILY_LOSS_LIMIT), ama backward için property
    @property
    def daily_loss_limit_amount(self):  # pylint: disable=missing-function-docstring
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


# Singleton instance for backward compatibility
config = Config()
