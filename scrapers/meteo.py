"""Meteo forecast scraper module querying Open-Meteo and WeatherAPI."""

import logging
import requests
from datetime import datetime
from database.db import get_session
from database.models import WeatherMarket, WeatherForecast
from config.settings import config, bot_config
from utils.retry import retry

logger = logging.getLogger("SCRAPER_METEO")


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
        """Open-Meteo API (ücretsiz, key gerekmez)."""
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
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        daily = data.get("daily", {})
        if daily.get("temperature_2m_max"):
            return {
                "source": "openmeteo",
                "temperature_max": daily["temperature_2m_max"][0],
                "temperature_min": daily["temperature_2m_min"][0],
                "precipitation_mm": daily["precipitation_sum"][0],
            }
        return None

    @retry(max_attempts=3, delay=3, exceptions=(requests.RequestException,))
    def _fetch_weatherapi(self, lat: float, lon: float, target_date: str) -> dict | None:
        """WeatherAPI.com."""
        if not bot_config.meteo.weatherapi_key:
            return None

        resp = requests.get(
            f"{bot_config.meteo.weatherapi_url}/forecast.json",
            params={
                "key": bot_config.meteo.weatherapi_key,
                "q": f"{lat},{lon}",
                "dt": target_date,
            },
            timeout=15
        )
        resp.raise_for_status()
        data = resp.json()

        day = data.get("forecast", {}).get("forecastday", [{}])[0].get("day", {})
        if day:
            return {
                "source": "weatherapi",
                "temperature_max": day.get("maxtemp_c"),
                "temperature_min": day.get("mintemp_c"),
                "precipitation_mm": day.get("totalprecip_mm"),
            }
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
