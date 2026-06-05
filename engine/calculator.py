"""Matematiksel formül ve olasılık hesabı (Normal Dağılım CDF)."""

import asyncio
import logging
from typing import Dict, Optional
from datetime import datetime, timezone
import aiohttp
from config.settings import config, Config

logger = logging.getLogger("WEATHER_ENGINE")

OPEN_METEO_MODEL_MAP = {
    "gfs_seamless": "gfs025",
    "ecmwf_ifs04": "ecmwf_ifs025",
    "gem_seamless": "gem_global",
    "icon_seamless": "icon_global",
    "jma_msm": "jma_seamless",
    "cma_grapes_global": "cma_grapes_global",
    "ukmo_seamless": "ukmo_seamless",
    "meteofrance_seamless": "meteofrance_seamless",
}

OPEN_METEO_MODEL_REVERSE = {v: k for k, v in OPEN_METEO_MODEL_MAP.items()}

try:
    from scipy.stats import norm
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    logger.warning("scipy not available, using Abramowitz & Stegun approximation for Normal CDF")


class WeatherEngine:
    """Multi-model ensemble weather forecast engine."""

    def __init__(self, db_session_factory=None, cfg=None):
        self.db_session_factory = db_session_factory
        self.config = cfg or config
        self.session: Optional[aiohttp.ClientSession] = None
        self.model_weights = self.config.get_normalized_weights()

    async def start(self):
        """Initialize HTTP session."""
        if self.session is None:
            self.session = aiohttp.ClientSession()
            logger.info("WeatherEngine HTTP session started")

    async def stop(self):
        """Close HTTP session."""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None
            logger.info("WeatherEngine HTTP session stopped")

    async def get_multi_model_forecast(
        self,
        city_code: str,
        latitude: float,
        longitude: float,
        target_date: Optional[datetime] = None,
    ) -> Optional[Dict]:
        """Get multi-model ensemble forecast for a specific location."""
        if not city_code or (latitude == 0 and longitude == 0):
            logger.warning(
                "Invalid location: city_code=%s, lat=%s, lon=%s",
                city_code,
                latitude,
                longitude,
            )
            return None

        if target_date is None:
            target_date = datetime.now(timezone.utc)

        api_model_names = []
        for internal_name in self.model_weights.keys():
            api_name = OPEN_METEO_MODEL_MAP.get(internal_name, internal_name)
            if api_name not in api_model_names:
                api_model_names.append(api_name)
        models_str = ",".join(api_model_names)

        url = f"{Config.OPEN_METEO_API}/forecast"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
            "models": models_str,
            "forecast_days": 14,
        }

        try:
            if not self.session or self.session.closed:
                await self.start()

            async with self.session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    logger.error("Open-Meteo API error: %s", resp.status)
                    return None

                data = await resp.json()
                model_temps = {}
                daily_data = data.get("daily", {})

                times = daily_data.get("time", [])
                if not times:
                    return None

                target_idx = None
                target_str = target_date.strftime("%Y-%m-%d")
                for i, t in enumerate(times):
                    if t.startswith(target_str):
                        target_idx = i
                        break

                if target_idx is None:
                    logger.warning("Target date %s not found in forecast", target_str)
                    return None

                for internal_name in self.model_weights.keys():
                    api_name = OPEN_METEO_MODEL_MAP.get(internal_name, internal_name)
                    key = f"temperature_2m_max_{api_name}"
                    if key in daily_data:
                        temps = daily_data[key]
                        if target_idx < len(temps) and temps[target_idx] is not None:
                            model_temps[internal_name] = temps[target_idx]

                if not model_temps:
                    logger.warning("No model data available for %s", city_code)
                    return None

                return self._calculate_deb_consensus(model_temps, target_date)

        except asyncio.TimeoutError:
            logger.error("Timeout fetching weather for %s", city_code)
            return None
        except Exception:
            logger.exception("Error fetching weather for %s", city_code)
            return None

    def _calculate_deb_consensus(self, model_temps: Dict[str, float], _target_date: datetime) -> Dict:
        """Calculate DEB (Deterministic Ensemble Blend) Consensus."""
        if not model_temps:
            return None

        total_weight = 0.0
        weighted_sum = 0.0

        for model_name, temp in model_temps.items():
            weight = self.model_weights.get(model_name, 0.0)
            weighted_sum += weight * temp
            total_weight += weight

        if total_weight == 0:
            return None

        weighted_mean = weighted_sum / total_weight

        weighted_var = 0.0
        for model_name, temp in model_temps.items():
            weight = self.model_weights.get(model_name, 0.0)
            weighted_var += weight * (temp - weighted_mean) ** 2

        weighted_std = (weighted_var / total_weight) ** 0.5
        weighted_std = max(weighted_std, 0.5)

        logger.info(
            "DEB Consensus: mean=%.2fC, std=%.2fC, models=%d",
            weighted_mean,
            weighted_std,
            len(model_temps),
        )

        return {
            "weighted_mean": weighted_mean,
            "weighted_std": weighted_std,
            "model_count": len(model_temps),
            "model_temps": model_temps,
            "timestamp": datetime.now(timezone.utc),
        }

    def calculate_probability_above(self, strike_temp: float, consensus: Dict) -> float:
        """Calculate P(Temp > Strike) using Normal CDF."""
        if not consensus:
            return 0.5

        mean = consensus["weighted_mean"]
        std = consensus["weighted_std"]
        z = (strike_temp - mean) / std

        if HAS_SCIPY:
            prob_below = norm.cdf(z)
        else:
            prob_below = self._normal_cdf(z)

        prob_above = 1.0 - prob_below
        return prob_above

    def calculate_probability_below(self, strike_temp: float, consensus: Dict) -> float:
        """Calculate P(Temp < Strike) using Normal CDF."""
        if not consensus:
            return 0.5

        mean = consensus["weighted_mean"]
        std = consensus["weighted_std"]
        z = (strike_temp - mean) / std

        if HAS_SCIPY:
            return norm.cdf(z)
        return self._normal_cdf(z)

    def _normal_cdf(self, z: float) -> float:
        """Standard Normal CDF using Abramowitz & Stegun approximation."""
        if z < -8:
            return 0.0
        if z > 8:
            return 1.0

        b1 = 0.319381530
        b2 = -0.356563782
        b3 = 1.781477937
        b4 = -1.821255978
        b5 = 1.330274429
        p = 0.2316419

        if z >= 0:
            t = 1.0 / (1.0 + p * z)
            poly = t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))
            return (
                1.0
                - (1.0 / (2.0 * 3.141592653589793**0.5))
                * (2.718281828459045 ** (-z * z / 2))
                * poly
            )
        t = 1.0 / (1.0 - p * z)
        poly = t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))
        return (
            (1.0 / (2.0 * 3.141592653589793**0.5))
            * (2.718281828459045 ** (-z * z / 2))
            * poly
        )

    async def get_forecast(
        self,
        city_code: str,
        latitude: float,
        longitude: float,
        target_date: Optional[datetime] = None,
    ) -> Optional[Dict]:
        """Alias for get_multi_model_forecast for API compatibility."""
        return await self.get_multi_model_forecast(
            city_code, latitude, longitude, target_date
        )

    def update_model_weights(self, new_weights: dict):
        """Update weights from SIA Loop."""
        self.model_weights = new_weights
        logger.info(
            "WeatherEngine weights updated from SIA: %s...",
            list(new_weights.keys())[:3],
        )
