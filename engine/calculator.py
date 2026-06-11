"""Matematiksel olasılık, Kelly kriteri hesaplayıcısı ve WeatherEngine konsensüs birleşimi."""

import math
import logging
import asyncio
from typing import Dict, List, Optional
from datetime import datetime, timezone
import aiohttp
from config.settings import config, bot_config, Config
from database.db import get_session
from database.models import WeatherMarket, WeatherForecast, Analysis, Portfolio
from utils.price_sanity import is_valid_binary_price

logger = logging.getLogger("ENGINE_CALCULATOR")

try:
    from scipy.stats import norm
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    logger.warning("scipy not available, using Abramowitz & Stegun approximation for Normal CDF")


class Calculator:
    """Calculates forecasting probability, Kelly stake sizes, and analyzes markets."""

    def estimate_probability(self, forecasts: List[float], threshold: float, days_ahead: int) -> float:
        """
        Tahmin değerlerinden, eşik aşılma olasılığını hesapla.
        P(X > threshold) hesapla.
        """
        if not forecasts:
            return 0.5

        mean = sum(forecasts) / len(forecasts)

        if len(forecasts) > 1:
            variance = sum((x - mean) ** 2 for x in forecasts) / (len(forecasts) - 1)
            std = math.sqrt(variance)
        else:
            std = 2.0  # Default 2C uncertainty for single source

        uncertainty_per_day = 0.5
        total_std = math.sqrt(std**2 + (days_ahead * uncertainty_per_day)**2)
        total_std = max(total_std, 1.0)

        z = (threshold - mean) / total_std

        if HAS_SCIPY:
            prob_below = norm.cdf(z)
        else:
            prob_below = self._normal_cdf(z)

        prob_above = 1.0 - prob_below
        return max(0.01, min(0.99, prob_above))

    def kelly_criterion(self, prob: float, price: float, fraction: float = 0.15) -> float:
        """Pure f* fraction.

        Parameter ``price`` is the *market price* of the bet (0..1), the
        same convention the in-process callers use
        (``market_implied = market.yes_price``). The decimal odds are
        computed internally as ``1/price - 1``.

        Note: the parameter is still named in the public signature to
        preserve the legacy call sites in :func:`analyze_market`, but
        callers should treat it as a price, not as a decimal odd.
        """
        if price <= 0 or price >= 1 or prob <= 0 or prob >= 1:
            return 0.0
        b = (1.0 / price) - 1.0
        if b <= 0:
            return 0.0
        q = 1.0 - prob
        f_star = (b * prob - q) / b
        if f_star <= 0:
            return 0.0
        return f_star * fraction

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
            return 1.0 - (1.0 / (2.0 * math.pi**0.5)) * (math.e ** (-z * z / 2)) * poly
        
        t = 1.0 / (1.0 - p * z)
        poly = t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))
        return (1.0 / (2.0 * math.pi**0.5)) * (math.e ** (-z * z / 2)) * poly

    def analyze_market(self, market_id: str) -> Analysis | None:
        """Bir marketi analiz et."""
        with get_session() as session:
            market = session.query(WeatherMarket).filter_by(id=market_id).first()
            if not market:
                logger.warning(f"Market bulunamadı: {market_id}")
                return None

            if not all([market.city, market.threshold, market.target_date, market.metric]):
                logger.warning(f"Market eksik bilgi: {market_id}")
                return None

            # Price sanity check - skip invalid binary markets
            if not is_valid_binary_price(market.yes_price or 0, market.no_price or 0):
                logger.debug(
                    f"Market {market_id}: invalid prices "
                    f"yes={market.yes_price}, no={market.no_price}, skipping"
                )
                return None

            # Skip already-resolved markets (lookahead bias guard)
            if market.target_date <= datetime.now(timezone.utc).replace(tzinfo=None):
                logger.debug(f"Market {market_id}: target_date {market.target_date} already passed, skipping")
                return None

            # Skip markets with no real liquidity (price too low for paper realism)
            market_price = market.yes_price or 0.5
            min_price = getattr(bot_config, "MIN_ENTRY_PRICE", 0.01) if hasattr(bot_config, "MIN_ENTRY_PRICE") else 0.01
            if market_price < min_price:
                logger.debug(f"Market {market_id}: price {market_price:.4f} < min {min_price}, skipping")
                return None

            # En son tahminleri al — query by market.metric directly.
            forecasts = session.query(WeatherForecast).filter(
                WeatherForecast.market_id == market_id,
                WeatherForecast.metric == market.metric,
            ).order_by(WeatherForecast.fetched_at.desc()).all()

            # Her kaynaktan en son tahmini al
            latest_by_source = {}
            for f in forecasts:
                if f.source not in latest_by_source:
                    latest_by_source[f.source] = f.predicted_value

            forecast_values = list(latest_by_source.values())

            if len(forecast_values) < bot_config.strategy.min_sources:
                logger.info(
                    f"Market {market_id}: Yetersiz kaynak "
                    f"({len(forecast_values)}/{bot_config.strategy.min_sources})"
                )

            # days_ahead: use calendar days (>=0) and treat "today" as 1 day
            # so that (target_date=23:59:59, now=04:21) -> 0 still means "today".
            days_ahead = (market.target_date - datetime.now(timezone.utc).replace(tzinfo=None)).days
            days_ahead_for_check = max(days_ahead, 1)

            # Olasılık hesapla
            estimated_prob = self.estimate_probability(
                forecast_values, market.threshold, days_ahead_for_check
            )

            market_implied = market.yes_price or 0.5
            edge = estimated_prob - market_implied

            if edge > 0:
                # YES tarafı
                kelly_frac = self.kelly_criterion(
                    estimated_prob, market_implied,
                    bot_config.strategy.kelly_fraction
                )
                recommended_side = "YES"
            else:
                # NO tarafı
                no_prob = 1 - estimated_prob
                no_implied = market.no_price or (1 - market_implied)
                no_edge = no_prob - no_implied

                if no_edge > 0:
                    kelly_frac = self.kelly_criterion(
                        no_prob, no_implied,
                        bot_config.strategy.kelly_fraction
                    )
                    recommended_side = "NO"
                    edge = no_edge
                else:
                    kelly_frac = 0
                    recommended_side = None

            # Bet miktarı — gerçek portföyden oku
            portfolio = session.query(Portfolio).filter(Portfolio.id == 1).first()
            bankroll = portfolio.total_value if portfolio and portfolio.total_value else 1000.0
            recommended_amount = min(
                kelly_frac * bankroll,
                bot_config.strategy.max_bet_amount
            )

            # Bet açılmalı mı?
            # NOTE: Polymarket'te public-search'ten gelen marketlerin
            # `liquidity` alanı genelde 0 (price bize zaten gerçek bilgi veriyor),
            # bu yüzden likidite kontrolünü kaldırıyoruz "” gerçek piyasa sinyali
            # `volume` veya `volume24hr` alanlarından biridir; bunlar da yoksa
            # `current_price` zaten likiditeyi yansıtır.
            # Yine de kullanıcı isterse `bot_config.strategy.min_liquidity`
            # değerini 0 yaparak bunu bypass edebilir.
            liquidity_ok = (
                (market.liquidity or 0) >= bot_config.strategy.min_liquidity
                or bot_config.strategy.min_liquidity <= 0
            )
            effective_min_edge = self._compute_effective_min_edge(market)
            should_bet = (
                abs(edge) >= effective_min_edge
                and len(forecast_values) >= bot_config.strategy.min_sources
                and 0 <= days_ahead <= bot_config.strategy.max_days_ahead
                and liquidity_ok
                and recommended_amount > 1.0
            )

            reason_parts = []
            if abs(edge) < effective_min_edge:
                reason_parts.append(f"Edge düşük: {edge:.2%}")
            if len(forecast_values) < bot_config.strategy.min_sources:
                reason_parts.append(f"Az kaynak: {len(forecast_values)}")
            if days_ahead > bot_config.strategy.max_days_ahead:
                reason_parts.append(f"Ã‡ok uzak: {days_ahead} gün")
            if (market.liquidity or 0) < bot_config.strategy.min_liquidity:
                reason_parts.append(f"Düşük likidite: ${market.liquidity}")

            if not reason_parts:
                reason = f"BET AÃ‡! Edge={edge:.2%}, Side={recommended_side}"
            else:
                reason = "PASS: " + ", ".join(reason_parts)

            avg_val = sum(forecast_values) / len(forecast_values) if forecast_values else None
            std_val = (
                math.sqrt(
                    sum((x - avg_val)**2 for x in forecast_values)
                    / len(forecast_values)
                ) if forecast_values and len(forecast_values) > 1 else None
            )

            analysis = Analysis(
                market_id=market_id,
                estimated_probability=estimated_prob,
                market_implied_prob=market_implied,
                edge=edge,
                avg_forecast_value=avg_val,
                std_forecast_value=std_val,
                num_sources=len(forecast_values),
                recommended_side=recommended_side,
                recommended_amount=recommended_amount,
                confidence_score=min(len(forecast_values) / 5, 1.0),
                should_bet=should_bet,
                reason=reason,
                analyzed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            session.add(analysis)
            logger.info(
                f"Market {market_id}: prob={estimated_prob:.2%}, "
                f"market={market_implied:.2%}, edge={edge:.2%}, "
                f"should_bet={should_bet}"
            )
            return analysis


    @staticmethod
    def _compute_effective_min_edge(market) -> float:
        """Time-to-close-scaled min_edge.

        Linearly ramps from 1x bot_config.strategy.min_edge at
        edge_escalation_hours before resolution to
        edge_escalation_multiplier * min_edge at the moment of close.
        Clamps to the multiplier if we are already past resolution, and
        never divides by zero.

        Mirrors WeatherEngine._compute_effective_min_edge (kept on
        WeatherEngine for backward-compat with tests). The single
        source of truth should eventually move to a module-level
        function; until then both copies must stay in sync.
        """
        s = bot_config.strategy
        try:
            resolution = (
                getattr(market, 'resolution_date', None)
                or getattr(market, 'target_date', None)
            )
            if resolution is None:
                return s.min_edge
            now = datetime.now(timezone.utc)
            if getattr(resolution, 'tzinfo', None) is None:
                resolution = resolution.replace(tzinfo=timezone.utc)
            hours_left = (resolution - now).total_seconds() / 3600.0
        except Exception:
            return s.min_edge

        # 60s tolerance for the boundary: a market created with
        # resolution_date=now+esc_h drifts microseconds by the time
        # the function runs, producing 0.01+1e-9 on CI. A 1-minute
        # window makes the boundary deterministic.
        if hours_left >= s.edge_escalation_hours - (60.0 / 3600.0):
            return s.min_edge
        if hours_left <= 0:
            return s.min_edge * s.edge_escalation_multiplier
        esc_h = max(1, s.edge_escalation_hours)
        fraction = hours_left / esc_h
        return s.min_edge * (
            1.0 + (s.edge_escalation_multiplier - 1.0) * (1.0 - fraction)
        )

# WeatherEngine kept for seamless FastAPI / backward compatibility
OPEN_METEO_MODEL_MAP = {
    "gfs_seamless": "gfs_seamless",
    "ecmwf_ifs04": "ecmwf_ifs025",
    "gem_seamless": "gem_global",
    "icon_seamless": "icon_global",
    "jma_msm": "jma_seamless",
    "cma_grapes_global": "cma_grapes_global",
    "ukmo_seamless": "ukmo_seamless",
    "meteofrance_seamless": "meteofrance_seamless",
}

METRIC_MAP = {
    "temperature_max": "temperature_2m_max",
    "temperature_min": "temperature_2m_min",
    "temperature_2m_max": "temperature_2m_max",
    "temperature_2m_min": "temperature_2m_min",
}


class WeatherEngine:
    """Weather engine consensus calculator (FastAPI / test compatibility wrapper)."""

    def __init__(self, db_session_factory=None, cfg=None):
        self.db_session_factory = db_session_factory
        self.config = cfg or config
        self.session: Optional[aiohttp.ClientSession] = None
        self.model_weights = self.config.get_normalized_weights()
        # Local cache for the current session to avoid redundant fetches (e.g. max/min overlap)
        self._forecast_cache = {}

    @staticmethod
    def _compute_effective_min_edge(market) -> float:
        """Return the time-to-close-scaled min_edge for market.

        Linearly ramps from 1x bot_config.strategy.min_edge at
        edge_escalation_hours before resolution to
        edge_escalation_multiplier * min_edge at the moment of close.
        Clamps to the multiplier if we are already past resolution, and
        never divides by zero.
        """
        s = bot_config.strategy
        try:
            resolution = (
                getattr(market, 'resolution_date', None)
                or getattr(market, 'target_date', None)
            )
            if resolution is None:
                return s.min_edge
            now = datetime.now(timezone.utc)
            if getattr(resolution, 'tzinfo', None) is None:
                resolution = resolution.replace(tzinfo=timezone.utc)
            hours_left = (resolution - now).total_seconds() / 3600.0
        except Exception:
            return s.min_edge

        # 60s tolerance for the boundary: a market created with
        # resolution_date=now+esc_h drifts microseconds by the time the
        # function runs, producing 0.01+1e-9 on CI. A 1-minute window
        # makes the boundary deterministic.
        if hours_left >= s.edge_escalation_hours - (60.0 / 3600.0):
            return s.min_edge
        if hours_left <= 0:
            return s.min_edge * s.edge_escalation_multiplier
        esc_h = max(1, s.edge_escalation_hours)
        fraction = hours_left / esc_h
        return s.min_edge * (
            1.0 + (s.edge_escalation_multiplier - 1.0) * (1.0 - fraction)
        )


    async def start(self):
        if self.session is None:
            self.session = aiohttp.ClientSession()

    async def stop(self):
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None

    async def get_multi_model_forecast(
        self,
        city_code: str,
        latitude: float,
        longitude: float,
        target_date: Optional[datetime] = None,
        market_ids: List[str] = None,
        db_session=None,
        metric: str = "temperature_2m_max",
    ) -> Optional[Dict]:
        if not city_code or (latitude == 0 and longitude == 0):
            return None
        if target_date is None:
            target_date = datetime.now(timezone.utc).replace(tzinfo=None)

        api_model_names = []
        for internal_name in self.model_weights.keys():
            api_name = OPEN_METEO_MODEL_MAP.get(internal_name, internal_name)
            if api_name not in api_model_names:
                api_model_names.append(api_name)
        models_str = ",".join(api_model_names)
        
        # Cache check
        target_str = target_date.strftime("%Y-%m-%d")
        cache_key = (round(latitude, 4), round(longitude, 4), target_str)
        if cache_key in self._forecast_cache:
            data = self._forecast_cache[cache_key]
            logger.debug("Ensemble cache hit for %s", cache_key)
        else:
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

                async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 429:
                        logger.warning("Ensemble API: Open-Meteo 429 Rate Limit! Waiting 30s...")
                        await asyncio.sleep(30)
                        return None
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    self._forecast_cache[cache_key] = data
            except Exception as e:
                logger.error("get_multi_model_forecast fetch error: %s", e)
                return None

        try:
            model_temps = {}
            daily_data = data.get("daily", {})
            times = daily_data.get("time", [])
            if not times:
                return None

            target_idx = None
            for i, t in enumerate(times):
                if t.startswith(target_str):
                    target_idx = i
                    break

            if target_idx is None:
                return None

                for internal_name in self.model_weights.keys():
                    api_name = OPEN_METEO_MODEL_MAP.get(internal_name, internal_name)
                    # Use the metric requested to pick the right daily data key
                    # although we fetch both max and min.
                    api_metric = "temperature_2m_max"
                    if "min" in metric.lower():
                        api_metric = "temperature_2m_min"
                    
                    key = f"{api_metric}_{api_name}"
                    if key in daily_data:
                        temps = daily_data[key]
                        if target_idx < len(temps) and temps[target_idx] is not None:
                            model_temps[internal_name] = temps[target_idx]

                if not model_temps:
                    return None

                # Calculate consensus
                total_weight = sum(self.model_weights.get(m, 0.0) for m in model_temps.keys())
                if total_weight == 0:
                    return None
                weighted_mean = sum(self.model_weights.get(m, 0.0) * t for m, t in model_temps.items()) / total_weight
                weighted_var = sum(self.model_weights.get(m, 0.0) * (t - weighted_mean)**2 for m, t in model_temps.items()) / total_weight
                weighted_std = max(weighted_var ** 0.5, 0.5)

                if db_session is not None and market_ids:
                    from database.models import WeatherForecast
                    for mid in market_ids:
                        for mn, tmp in model_temps.items():
                            db_session.add(WeatherForecast(
                                market_id=mid,
                                city=city_code,
                                lat=latitude,
                                lon=longitude,
                                target_date=target_date,
                                metric=metric,
                                source=mn,
                                predicted_value=float(tmp),
                                model_weight=self.model_weights.get(mn, 0.0),
                                fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
                                raw_data=str({"model": mn, "temp": tmp, "ensemble": True})
                            ))
                    try:
                        db_session.commit()
                        logger.info("Ensemble persisted for %d markets, coords=(%s, %s)", len(market_ids), latitude, longitude)
                    except Exception as e:
                        db_session.rollback()
                        logger.error("Failed to persist ensemble: %s", e)

                return {
                    "weighted_mean": weighted_mean,
                    "weighted_std": weighted_std,
                    "model_count": len(model_temps),
                    "model_temps": model_temps,
                    "timestamp": datetime.now(timezone.utc).replace(tzinfo=None),
                }
        except Exception as e:
            logger.error("get_multi_model_forecast error: %s", e)
            return None

    def _db_consensus(self, market_id: str) -> Optional[Dict]:
        if not market_id or not self.db_session_factory:
            return None
        db = self.db_session_factory()
        try:
            from database.models import WeatherForecast
            fcs = db.query(WeatherForecast).filter(WeatherForecast.market_id == market_id).order_by(WeatherForecast.fetched_at.desc()).limit(30).all()
            if not fcs:
                return None
            lat = {}
            for f in fcs:
                if f.source not in lat:
                    lat[f.source] = (f.predicted_value, self.model_weights.get(f.source, 0.0))
            tw = sum(w for _, w in lat.values())
            if tw <= 0:
                vs = [v for v, _ in lat.values()]
                m = sum(vs) / len(vs)
                s = max((sum((v-m)**2 for v in vs)/len(vs))**0.5, 0.5) if len(vs)>1 else 1.0
                return {"weighted_mean": m, "weighted_std": s}
            wm = sum(v*w for v,w in lat.values()) / tw
            wv = sum(w*(v-wm)**2 for v,w in lat.values()) / tw
            return {"weighted_mean": wm, "weighted_std": max(wv**0.5, 0.5)}
        except Exception:
            return None
        finally:
            db.close()

    def calculate_probability_above(self, strike_temp: float, consensus=None, market_id=""):
        if not consensus:
            consensus = self._db_consensus(market_id)
        if not consensus:
            return 0.5
        mean = consensus["weighted_mean"]
        std = consensus["weighted_std"]
        z = (strike_temp - mean) / std
        if HAS_SCIPY:
            return 1.0 - norm.cdf(z)
        return 1.0 - self._normal_cdf(z)

    def calculate_probability_below(self, strike_temp: float, consensus=None, market_id=""):
        if not consensus:
            consensus = self._db_consensus(market_id)
        if not consensus:
            return 0.5
        mean = consensus["weighted_mean"]
        std = consensus["weighted_std"]
        z = (strike_temp - mean) / std
        if HAS_SCIPY:
            return norm.cdf(z)
        return self._normal_cdf(z)

    def _normal_cdf(self, z: float) -> float:
        if z < -8:
            return 0.0
        if z > 8:
            return 1.0
        b1, b2, b3, b4, b5 = 0.319381530, -0.356563782, 1.781477937, -1.821255978, 1.330274429
        p = 0.2316419
        if z >= 0:
            t = 1.0 / (1.0 + p * z)
            poly = t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))
            return 1.0 - (1.0 / (2.0 * math.pi**0.5)) * (math.e ** (-z * z / 2)) * poly
        t = 1.0 / (1.0 - p * z)
        poly = t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))
        return (1.0 / (2.0 * math.pi**0.5)) * (math.e ** (-z * z / 2)) * poly

    async def get_forecast(self, city_code: str, latitude: float, longitude: float, target_date: Optional[datetime] = None) -> Optional[Dict]:
        return await self.get_multi_model_forecast(city_code, latitude, longitude, target_date)

    def update_model_weights(self, new_weights: dict):
        self.model_weights = new_weights
