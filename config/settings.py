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
            "hurricane", "storm", "weather", "Â°F", "Â°C",
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
    # Lowered from 0.03 to 0.01 (1%): Polymarket temperature markets
    # in /public-search almost never produce 3%+ edge because the
    # market price already discounts the public NWS/Open-Meteo
    # consensus. 1% is enough to cover bookmaker vig + a thin profit
    # margin in paper mode. Can be raised back once a private weather
    # feed (e.g. ECMWF-direct) gives a structural edge.
    min_edge: float = 0.05           # 5% edge minimum (must exceed 2% fee_drag + margin)
    max_bet_amount: float = 30.0    # Maximum $50 per bet
    min_liquidity: float = 0.0      # Liquidity check disabled: Polymarket public-search
                                    # markets don't expose a `liquidity` field reliably
                                    # (it's always 0). The current_price already reflects
                                    # real market depth.
    kelly_fraction: float = 0.15    # Quarter/Fractional Kelly (aligned with QwenBot 15%)
    # Time-to-close edge escalation. As a market approaches its
    # resolution time, Polymarket prices move fast on the public
    # weather consensus and forecast uncertainty is already low.
    # We demand a stronger edge in the last N hours before close
    # so the bot is less willing to take a late bet at a thin edge.
    # Linear ramp: 1x min_edge at edge_escalation_hours, then
    # ramps to edge_escalation_multiplier * min_edge at 0h.
    edge_escalation_hours: int = 24
    edge_escalation_multiplier: float = 2.0
    # Time-to-close edge escalation. As a market approaches its
    # resolution time, Polymarket prices move fast on the public
    # weather consensus and forecast uncertainty is already low.
    # We demand a stronger edge in the last N hours before close
    # so the bot is less willing to take a late bet at a thin edge.
    # Linear ramp: 1x min_edge at edge_escalation_hours, then
    # ramps to edge_escalation_multiplier * min_edge at 0h.
    edge_escalation_hours: int = 24
    edge_escalation_multiplier: float = 2.0
    min_sources: int = 2            # En az 2 kaynak (openmeteo + weatherapi ile calisiyor)
    fee_drag: float = 0.02          # Polymarket taker fee %2
    # Bot scope: today + 1 + 2 days ahead (0..2 inclusive).
    # Tightened from 14 to 2 so the bot only trades near-term markets
    # where the public weather ensemble (GFS/ECMWF/ICON/...) is still
    # calibrated. Forecasts degrade past 3 days.
    max_days_ahead: int = 2


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
    # Minimum market price to place a bet. Bids at 0.001 have no real
    # liquidity on Polymarket; paper PnL at those levels is fantasy.
    MIN_ENTRY_PRICE = float(os.getenv("MIN_ENTRY_PRICE", "0.01"))
    # Fixed dollar amount per bet, set via FLAT_BET_USD env var.
    # 0.0 (default) means 'use the calculator's Kelly-based recommendation'.
    # > 0.0 means 'every bet is exactly this many USD, ignore Kelly sizing'.
    # Risk caps (MAX_BET_PCT, TOTAL_EXPOSURE_PCT, CITY_CAP) still apply on top.
    FLAT_BET_USD = float(os.getenv("FLAT_BET_USD", "0.0"))  # 0 = use Kelly sizing
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
        # Turkey (4)
        "ankara": "LTAC",
        "istanbul": "LTFM",
        "izmir": "LTBJ",
        "antalya": "LTAI",
        # North America - USA (15)
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
        "washington": "KDCA",
        "san francisco": "KSFO",
        "orlando": "KMCO",
        # North America - CA / MX (5)
        "toronto": "CYYZ",
        "vancouver": "CYVR",
        "montreal": "CYUL",
        "mexico city": "MMMX",
        "guadalajara": "MMGL",
        # South America (5)
        "sao paulo": "SBGR",
        "rio de janeiro": "SBGL",
        "buenos aires": "SAEZ",
        "santiago": "SCEL",
        "lima": "SPJC",
        # Europe (15)
        "london": "EGLL",
        "paris": "LFPG",
        "berlin": "EDDT",
        "moscow": "UUEE",
        "frankfurt": "EDDF",
        "amsterdam": "EHAM",
        "madrid": "LEMD",
        "rome": "LIRF",
        "barcelona": "LEBL",
        "munich": "EDDM",
        "zurich": "LSZH",
        "vienna": "LOWW",
        "stockholm": "ESSA",
        "athens": "LGAV",
        "lisbon": "LPPT",
        # Middle East (3)
        "dubai": "OMDB",
        "tel aviv": "LLBG",
        "doha": "OTHH",
        # Asia (12)
        "tokyo": "RJTT",
        "osaka": "RJOO",
        "shanghai": "ZSPD",
        "beijing": "ZBAA",
        "seoul": "RKSS",
        "hong kong": "VHHH",
        "taipei": "RCTP",
        "singapore": "WSSS",
        "bangkok": "VTBS",
        "jakarta": "WIII",
        "mumbai": "VABB",
        "delhi": "VIDP",
        # Oceania (3)
        "sydney": "YSSY",
        "melbourne": "YMML",
        "auckland": "NZAA",
        # Africa (2)
        "cairo": "HECA",
        "cape town": "FACT",
    }
    OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"
    FEE_DRAG = float(os.getenv("FEE_DRAG", "0.02"))
    # NOTE: minimum-edge threshold is NOT defined on Config on purpose.
    # The single source of truth is `bot_config.strategy.min_edge` (default 0.01 = 1%).
    # `engine.calculator.py` reads from there at lines 179 & 187; the previous
    # `Config.MIN_EDGE = 0.03` constant was dead code (never read anywhere) and
    # caused "which one is canonical?" confusion in code review.
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
