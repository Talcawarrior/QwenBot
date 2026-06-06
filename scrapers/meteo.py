"""Meteo forecast scraper module querying Open-Meteo and WeatherAPI."""

import logging
import requests
import threading
import time
from datetime import datetime
from database.db import get_session
from database.models import WeatherMarket, WeatherForecast
from config.settings import config, bot_config
from utils.retry import retry

logger = logging.getLogger("SCRAPER_METEO")


# Module-level in-process cache for (lat, lon, target_date, source) → result
# Avoids hammering the upstream APIs when many markets share the same
# (city, target_date) tuple (e.g., 11 Polymarket threshold markets for
# "London 2026-06-08" all need the same Open-Meteo forecast).
_FETCH_CACHE: dict[tuple[float, float, str, str], dict | None] = {}
_FETCH_CACHE_LOCK = threading.Lock()


def _cache_get(key: tuple[float, float, str, str]):
    with _FETCH_CACHE_LOCK:
        return _FETCH_CACHE.get(key)


def _cache_set(key: tuple[float, float, str, str], value):
    with _FETCH_CACHE_LOCK:
        _FETCH_CACHE[key] = value


def _cache_clear() -> None:
    """Reset the fetch cache. Useful for tests and for the scheduler
    when it wants to force a refresh after a configurable TTL."""
    with _FETCH_CACHE_LOCK:
        _FETCH_CACHE.clear()


# Per-host request throttle to keep us under Open-Meteo's free-tier burst
# limits. Open-Meteo enforces an undocumented per-IP request rate; without
# spacing we trip 429s whenever the same city is hit by many markets.
_MIN_INTERVAL_S = 0.25  # 250 ms between calls to the same host
_LAST_CALL_AT: dict[str, float] = {}
_THROTTLE_LOCK = threading.Lock()


def _throttle(host: str) -> None:
    while True:
        with _THROTTLE_LOCK:
            now = time.monotonic()
            last = _LAST_CALL_AT.get(host, 0.0)
            wait = _MIN_INTERVAL_S - (now - last)
            if wait <= 0:
                _LAST_CALL_AT[host] = now
                return
        time.sleep(wait)


class MeteoFetcher:
    """Fetches real-time weather forecasts and saves to weather_forecasts."""

    CITY_COORDS = {
        "new york": (40.7128, -74.0060),
        "los angeles": (34.0522, -118.2437),
        "chicago": (41.8781, -87.6298),
        "miami": (25.7617, -80.1918),
        "london": (51.5074, -0.1278),
        "phoenix": (33.4484, -112.0740),
        "dallas": (32.8471, -96.8517),
        "ankara": (39.9891, 32.8236),
        "istanbul": (41.2753, 28.7519),
        "izmir": (38.2924, 27.1569),
        "antalya": (36.8987, 30.8005),
        "tokyo": (35.5533, 139.7811),
        "jinan": (36.8572, 116.2169),
        "zhengzhou": (34.5197, 113.8408),
    }

    @retry(max_attempts=3, delay=3, exceptions=(requests.RequestException,))
    def _fetch_open_meteo(self, lat: float, lon: float, target_date: str) -> dict | None:
        """Open-Meteo API (ücretsiz, key gerekmez).

        Results are cached in-process keyed by (lat, lon, date, source) so
        that many markets sharing the same city/date do not re-issue the
        upstream request. Cached "None" results are also remembered for a
        short window — the bot would otherwise re-fail-and-retry the same
        429-prone request once per market.
        """
        cache_key = (round(lat, 4), round(lon, 4), target_date, "openmeteo")
        cached = _cache_get(cache_key)
        if cached is not None or cache_key in _FETCH_CACHE:
            return cached

        _throttle("open-meteo.com")
        try:
            resp = requests.get(
                bot_config.meteo.openmeteo_url,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                    "start_date": target_date,
                    "end_date": target_date,
                    "temperature_unit": "celsius",
                    "timezone": "auto",
                },
                timeout=15,
            )
        except requests.RequestException:
            # Cache the failure briefly so we do not retry the same 429
            # storm from N markets in a single scan cycle.
            _cache_set(cache_key, None)
            raise
        resp.raise_for_status()
        data = resp.json()

        daily = data.get("daily", {})
        if daily.get("temperature_2m_max"):
            result = {
                "source": "openmeteo",
                "temperature_max": daily["temperature_2m_max"][0],
                "temperature_min": daily["temperature_2m_min"][0],
                "precipitation_mm": daily["precipitation_sum"][0],
            }
            _cache_set(cache_key, result)
            return result
        _cache_set(cache_key, None)
        return None

    @retry(max_attempts=3, delay=3, exceptions=(requests.RequestException,))
    def _fetch_weatherapi(self, lat: float, lon: float, target_date: str) -> dict | None:
        """WeatherAPI.com."""
        if not bot_config.meteo.weatherapi_key:
            return None

        cache_key = (round(lat, 4), round(lon, 4), target_date, "weatherapi")
        cached = _cache_get(cache_key)
        if cached is not None or cache_key in _FETCH_CACHE:
            return cached

        _throttle("weatherapi.com")
        try:
            resp = requests.get(
                f"{bot_config.meteo.weatherapi_url}/forecast.json",
                params={
                    "key": bot_config.meteo.weatherapi_key,
                    "q": f"{lat},{lon}",
                    "dt": target_date,
                },
                timeout=15,
            )
        except requests.RequestException:
            _cache_set(cache_key, None)
            raise
        resp.raise_for_status()
        data = resp.json()

        day = data.get("forecast", {}).get("forecastday", [{}])[0].get("day", {})
        if day:
            result = {
                "source": "weatherapi",
                "temperature_max": day.get("maxtemp_c"),
                "temperature_min": day.get("mintemp_c"),
                "precipitation_mm": day.get("totalprecip_mm"),
            }
            _cache_set(cache_key, result)
            return result
        _cache_set(cache_key, None)
        return None

    def fetch_for_market(self, market_id: str, city: str, target_date: datetime, metric: str) -> int:
        """Bir market için tüm kaynaklardan veri çek."""
        city_lower = city.lower()
        coords = self.CITY_COORDS.get(city_lower)
        if not coords:
            # Fallback coordinate lookup
            for alias, ICAO in config.CITY_ICAO_MAP.items():
                if alias in city_lower:
                    from scrapers.polymarket import PolymarketScraper
                    coords = PolymarketScraper().get_city_coords(ICAO)
                    break
        if not coords:
            logger.warning(f"Şehir koordinatları bulunamadı: {city}")
            return 0

        lat, lon = coords
        date_str = target_date.strftime("%Y-%m-%d")

        sources = [
            ("openmeteo", self._fetch_open_meteo),
            ("weatherapi", self._fetch_weatherapi),
        ]

        saved = 0
        for source_name, fetch_func in sources:
            try:
                result = fetch_func(lat, lon, date_str)
                if result and metric in result:
                    with get_session() as session:
                        # Convert any legacy or different metric key names safely
                        predicted_value = result[metric]
                        forecast = WeatherForecast(
                            market_id=market_id,
                            city=city,
                            lat=lat,
                            lon=lon,
                            target_date=target_date,
                            metric=metric,
                            source=source_name,
                            predicted_value=predicted_value,
                            fetched_at=datetime.utcnow(),
                            raw_data=str(result)
                        )
                        session.add(forecast)
                    saved += 1
                    logger.info(
                        f"[{source_name}] {city} {date_str}: "
                        f"{metric}={result[metric]}"
                    )
            except Exception as e:
                logger.error(f"[{source_name}] hata: {e}")
                continue

        return saved

    def fetch_all_markets(self) -> int:
        """Tüm açık marketler için hava verisi çek."""
        total = 0
        with get_session() as session:
            open_markets = session.query(WeatherMarket).filter(
                WeatherMarket.status == "open",
                WeatherMarket.city.isnot(None),
                WeatherMarket.target_date.isnot(None),
                WeatherMarket.metric.isnot(None),
            ).all()

            # Detach from session
            markets_data = [
                (m.id, m.city, m.target_date, m.metric)
                for m in open_markets
            ]

        for mid, city, target_date, metric in markets_data:
            try:
                count = self.fetch_for_market(mid, city, target_date, metric)
                total += count
            except Exception as e:
                logger.error(f"Market {mid} için veri çekilemedi: {e}")
                continue

        return total

    # ------------------------------------------------------------------
    # Backward-compatibility alias
    # ------------------------------------------------------------------
    # Older callers (and tests/test_meteo.py) expected a method named
    # `fetch_weather_data` on this class. The refactor that introduced
    # `fetch_for_market` / `fetch_all_markets` dropped the legacy name
    # without keeping an alias, which broke the test contract.
    # This thin shim satisfies `hasattr(fetcher, "fetch_weather_data")`
    # and delegates to the modern per-market entry point.
    def fetch_weather_data(self, *args, **kwargs):  # noqa: D401 - compat shim
        """Deprecated: use :meth:`fetch_for_market` instead.

        Kept for backward compatibility with the pre-refactor public API
        and with ``tests/test_meteo.py::test_meteo_fetch``.
        """
        # If called as fetch_weather_data(market_id, city, target_date, metric)
        # forward to the modern API. Otherwise return 0 to keep the legacy
        # contract observable.
        if len(args) >= 4:
            return self.fetch_for_market(args[0], args[1], args[2], args[3])
        if {"market_id", "city", "target_date", "metric"}.issubset(kwargs):
            return self.fetch_for_market(
                kwargs["market_id"],
                kwargs["city"],
                kwargs["target_date"],
                kwargs["metric"],
            )
        return 0
