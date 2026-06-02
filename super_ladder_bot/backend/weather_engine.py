"""
Weather Engine - 8+ Hava Durumu Modeli Entegrasyonu
Open-Meteo API kullanarak tüm modellerden veri çeker
"""
import aiohttp
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from config import config

logger = logging.getLogger(__name__)


class WeatherEngine:
    """Multi-model weather forecast engine"""
    
    def __init__(self):
        self.endpoints = config.OPENMETEO_ENDPOINTS
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def start(self):
        """HTTP session başlat"""
        self.session = aiohttp.ClientSession()
        logger.info("Weather engine started")
    
    async def stop(self):
        """HTTP session kapat"""
        if self.session:
            await self.session.close()
            logger.info("Weather engine stopped")
    
    async def get_forecast(
        self, 
        lat: float, 
        lon: float, 
        model: str = "gfs"
    ) -> Optional[Dict]:
        """
        Belirli bir model için hava durumu tahmini al
        
        Args:
            lat: Latitude
            lon: Longitude
            model: Model adı (gfs, ecmwf, cma, jma, kma, dwd_icon, meteofrance, ukmo)
        
        Returns:
            Forecast data dictionary veya None
        """
        if not self.session:
            await self.start()
        
        endpoint = self.endpoints.get(model)
        if not endpoint:
            logger.warning(f"Unknown model: {model}")
            return None
        
        # Günlük sıcaklık verileri (min, max)
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
            "forecast_days": 7
        }
        
        try:
            async with self.session.get(
                f"{endpoint}/forecast",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return self._parse_forecast(data, model)
                else:
                    logger.error(f"API error for {model}: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Forecast error ({model}): {e}")
            return None
    
    def _parse_forecast(self, data: Dict, model: str) -> Dict:
        """Ham API yanıtını parse et"""
        daily = data.get('daily', {})
        
        forecasts = []
        dates = daily.get('time', [])
        max_temps = daily.get('temperature_2m_max', [])
        min_temps = daily.get('temperature_2m_min', [])
        
        for i in range(len(dates)):
            forecasts.append({
                'date': dates[i],
                'max_temp_f': self._celsius_to_fahrenheit(max_temps[i]) if i < len(max_temps) else None,
                'min_temp_f': self._celsius_to_fahrenheit(min_temps[i]) if i < len(min_temps) else None,
            })
        
        return {
            'model': model,
            'location': {
                'lat': data.get('latitude'),
                'lon': data.get('longitude')
            },
            'forecasts': forecasts,
            'generated_at': datetime.now().isoformat()
        }
    
    async def get_multi_model_forecast(
        self, 
        lat: float, 
        lon: float,
        city_name: str = "Unknown"
    ) -> Dict:
        """
        Tüm modellerden paralel veri çek (8+ Model - NOWBot Standardı)
        Ensemble forecast için kullanılır
        
        Args:
            lat: Latitude
            lon: Longitude
            city_name: Şehir adı (log için)
        
        Returns:
            All model forecasts + DEB Consensus
        """
        logger.info(f"Fetching weather data for {city_name} ({lat}, {lon})")
        
        tasks = [
            self.get_forecast(lat, lon, model)
            for model in self.endpoints.keys()
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        model_forecasts = {}
        valid_count = 0
        
        for model, result in zip(self.endpoints.keys(), results):
            if isinstance(result, Exception):
                logger.error(f"Model {model} failed: {result}")
                continue
            if result:
                model_forecasts[model] = result
                valid_count += 1
        
        logger.info(f"Weather data fetched for {city_name}: {valid_count}/{len(self.endpoints)} models OK")
        
        # DEB Consensus hesapla (config'deki ağırlıklarla)
        deb_consensus = self._calculate_deb_consensus(model_forecasts)
        
        return {
            'models': model_forecasts,
            'deb_consensus': deb_consensus,
            'valid_models': valid_count,
            'total_models': len(self.endpoints),
            'generated_at': datetime.now().isoformat()
        }
    
    def _calculate_deb_consensus(self, model_forecasts: Dict) -> Dict:
        """
        DEB Consensus hesapla (PolyTempAI Standardı)
        Config'deki model ağırlıklarını kullanarak weighted mean ve std dev
        
        Args:
            model_forecasts: Her modelin forecast verisi
        
        Returns:
            DEB Consensus: weighted_mean, weighted_std, confidence
        """
        if not model_forecasts:
            return None
        
        from config import config
        normalized_weights = config.get_normalized_model_weights()
        
        # Her gün için DEB consensus hesapla
        all_forecasts = list(model_forecasts.values())
        if not all_forecasts:
            return None
        
        first_model = all_forecasts[0]
        consensus_forecasts = []
        
        for i, forecast_day in enumerate(first_model.get('forecasts', [])):
            date = forecast_day.get('date')
            
            # Her modelin o günkü tahminini topla
            temps = []
            weights_used = []
            
            for model_name, model_data in model_forecasts.items():
                if i < len(model_data.get('forecasts', [])):
                    day_data = model_data['forecasts'][i]
                    max_temp = day_data.get('max_temp_f')
                    min_temp = day_data.get('min_temp_f')
                    
                    if max_temp is not None and min_temp is not None:
                        avg_temp = (max_temp + min_temp) / 2
                        weight = normalized_weights.get(model_name, 0.05)
                        temps.append(avg_temp)
                        weights_used.append(weight)
            
            if not temps:
                continue
            
            # Weighted mean
            total_weight = sum(weights_used)
            if total_weight == 0:
                continue
            
            weighted_mean = sum(t * w for t, w in zip(temps, weights_used)) / total_weight
            
            # Weighted std dev (variance pooling)
            weighted_var = sum(
                w * ((t - weighted_mean) ** 2) 
                for t, w in zip(temps, weights_used)
            ) / total_weight
            weighted_std = weighted_var ** 0.5
            
            # Confidence: model agreement ne kadar yüksekse o kadar iyi
            # Std dev düşük = yüksek confidence
            confidence = max(0, 1 - (weighted_std / 10))  # Normalize 0-1
            
            consensus_forecasts.append({
                'date': date,
                'weighted_mean_temp': round(weighted_mean, 2),
                'weighted_std': round(weighted_std, 2),
                'confidence': round(confidence, 4),
                'num_models': len(temps)
            })
        
        # Genel istatistikler
        all_temps = [f['weighted_mean_temp'] for f in consensus_forecasts if f]
        avg_confidence = sum(f['confidence'] for f in consensus_forecasts if f) / len(consensus_forecasts) if consensus_forecasts else 0
        
        return {
            'forecasts': consensus_forecasts,
            'avg_confidence': round(avg_confidence, 4),
            'avg_temp': round(sum(all_temps) / len(all_temps), 2) if all_temps else None,
            'temp_range': {
                'min': round(min(all_temps), 2) if all_temps else None,
                'max': round(max(all_temps), 2) if all_temps else None
            }
        }
    
    def _calculate_ensemble(self, model_forecasts: Dict) -> Dict:
        """
        Multi-model ensemble hesapla
        Ortalama, standart sapma, confidence
        """
        if not model_forecasts:
            return None
        
        # Her gün için ensemble hesapla
        all_forecasts = list(model_forecasts.values())
        if not all_forecasts:
            return None
        
        first_model = all_forecasts[0]
        ensemble_forecasts = []
        
        # İlk modelin tarihlerini kullan
        for i, forecast in enumerate(first_model['forecasts']):
            date = forecast['date']
            
            # Tüm modellerden bu günün verilerini topla
            max_temps = []
            min_temps = []
            
            for model_data in all_forecasts:
                if i < len(model_data['forecasts']):
                    m = model_data['forecasts'][i]
                    if m['max_temp_f'] is not None:
                        max_temps.append(m['max_temp_f'])
                    if m['min_temp_f'] is not None:
                        min_temps.append(m['min_temp_f'])
            
            if max_temps and min_temps:
                ensemble_forecasts.append({
                    'date': date,
                    'avg_max_temp': sum(max_temps) / len(max_temps),
                    'avg_min_temp': sum(min_temps) / len(min_temps),
                    'max_temp_std': self._std_dev(max_temps) if len(max_temps) > 1 else 0,
                    'min_temp_std': self._std_dev(min_temps) if len(min_temps) > 1 else 0,
                    'num_models': len(max_temps),
                    'consensus': len(max_temps) >= len(all_forecasts) * 0.6  # %60 consensus
                })
        
        return {
            'forecasts': ensemble_forecasts,
            'num_models': len(model_forecasts)
        }
    
    def _celsius_to_fahrenheit(self, celsius: float) -> float:
        """Celsius'u Fahrenheit'a çevir"""
        if celsius is None:
            return None
        return (celsius * 9/5) + 32
    
    def _std_dev(self, values: List[float]) -> float:
        """Standart sapma hesapla"""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
    
    async def get_temperature_probability(
        self,
        lat: float,
        lon: float,
        strike_temp: float,
        side: str,
        target_date: str
    ) -> Dict:
        """
        Belirli bir sıcaklık seviyesinin üzerine/altına düşme olasılığını hesapla
        
        Args:
            lat: Latitude
            lon: Longitude
            strike_temp: Strike temperature (°F)
            side: "YES" (above) veya "NO" (below)
            target_date: Hedef tarih (YYYY-MM-DD)
        
        Returns:
            Probability calculation result
        """
        multi_forecast = await self.get_multi_model_forecast(lat, lon)
        
        if not multi_forecast or not multi_forecast['ensemble']:
            return {'probability': 0.5, 'confidence': 0.0, 'error': 'No forecast data'}
        
        # Hedef tarihin forecast'ini bul
        target_forecast = None
        for forecast in multi_forecast['ensemble']['forecasts']:
            if forecast['date'] == target_date:
                target_forecast = forecast
                break
        
        if not target_forecast:
            return {'probability': 0.5, 'confidence': 0.0, 'error': 'Target date not found'}
        
        # Basit probability modeli (normal dağılım varsayımı)
        avg_temp = target_forecast['avg_max_temp']
        std_dev = target_forecast['max_temp_std']
        
        if std_dev == 0:
            std_dev = 2.0  # Minimum uncertainty
        
        # Z-score hesapla
        z_score = (strike_temp - avg_temp) / std_dev
        
        # Cumulative distribution function approximation
        probability = self._normal_cdf(z_score)
        
        # Side'a göre ayarla
        if side == "YES":  # Temperature ABOVE strike
            probability = 1 - probability
        else:  # Temperature BELOW strike
            probability = probability
        
        # Confidence hesapla (model consensus + low std dev = high confidence)
        consensus_ratio = target_forecast['num_models'] / multi_forecast['ensemble']['num_models']
        confidence = min(1.0, consensus_ratio * (1 - min(std_dev / 10, 0.5)))
        
        return {
            'probability': round(probability, 4),
            'confidence': round(confidence, 4),
            'avg_temperature': round(avg_temp, 2),
            'std_deviation': round(std_dev, 2),
            'z_score': round(z_score, 2),
            'num_models': target_forecast['num_models'],
            'consensus': target_forecast['consensus'],
            'target_date': target_date,
            'strike_temp': strike_temp,
            'side': side
        }
    
    def _normal_cdf(self, x: float) -> float:
        """Normal dağılım cumulative distribution function approximation"""
        # Approximation using error function
        return 0.5 * (1 + self._erf(x / 2**0.5))
    
    def _erf(self, x: float) -> float:
        """Error function approximation"""
        # Constants
        a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
        p = 0.3275911
        
        sign = 1 if x >= 0 else -1
        x = abs(x)
        
        t = 1.0 / (1.0 + p * x)
        y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
        
        return sign * y


# Import asyncio ve math
import asyncio
import math

# Singleton instance
weather_engine = WeatherEngine()
