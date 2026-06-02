"""
Betting Engine - Kelly Criterion + Edge + EV Hesaplama
Fractional Kelly (%15) + Smart Pool (%40) ile pozisyon boyutlandırma
PolyTempAI Standardı: DEB Consensus + Normal CDF
"""
import logging
import math
from typing import Dict, Optional, List
from config import config

logger = logging.getLogger(__name__)


class BettingEngine:
    """Pozisyon boyutlandırma ve sinyal analizi"""
    
    def __init__(self):
        self.kelly_fraction = config.KELLY_FRACTION  # %15 Fractional Kelly
        self.max_bet_pct = config.MAX_BET_PCT  # %3 Hard Cap
        self.edge_threshold = config.EDGE_THRESHOLD  # %3 Minimum Edge
        self.smart_pool_pct = config.SMART_POOL_PCT  # %40 Akıllı Havuz
    
    def normal_cdf(self, x: float) -> float:
        """
        Normal Distribution CDF (Abramowitz & Stegun yaklaşımı)
        PolyTempAI standardı - olasılık hesabında endüstri standardı
        
        Args:
            x: Z-score
        
        Returns:
            CDF değeri (0-1 arası)
        """
        # Constants for Abramowitz & Stegun approximation
        a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
        p = 0.3275911
        
        # Save the sign of x
        sign = 1 if x >= 0 else -1
        x = abs(x) / math.sqrt(2)
        
        # A&S formula 7.1.26
        t = 1.0 / (1.0 + p * x)
        y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
        
        return 0.5 * (1.0 + sign * y)
    
    def calculate_deb_probability(
        self,
        model_forecasts: List[Dict],
        strike_temp: float,
        bet_type: str  # "HIGH" or "LOW"
    ) -> float:
        """
        DEB Consensus ile olasılık hesapla (Normal CDF kullanarak)
        
        Args:
            model_forecasts: Her modelin tahmini ve ağırlığı
                [{"model": "gfs", "temp": 85.5, "weight": 0.45, "std": 3.2}, ...]
            strike_temp: Strike sıcaklık
            bet_type: "HIGH" (Temp > Strike) veya "LOW" (Temp < Strike)
        
        Returns:
            P(Temp > Strike) veya P(Temp < Strike)
        """
        if not model_forecasts:
            return 0.5
        
        # Weighted mean hesapla
        weighted_sum = sum(f["temp"] * f["weight"] for f in model_forecasts)
        total_weight = sum(f["weight"] for f in model_forecasts)
        weighted_mean = weighted_sum / total_weight if total_weight > 0 else 0
        
        # Weighted std dev hesapla (variance pooling)
        weighted_var = sum(
            f["weight"] * (f.get("std", 3.0) ** 2) 
            for f in model_forecasts
        ) / total_weight
        weighted_std = math.sqrt(weighted_var) if weighted_var > 0 else 3.0
        
        # Z-score hesapla
        z_score = (strike_temp - weighted_mean) / weighted_std
        
        # Normal CDF ile olasılık hesapla
        cdf_value = self.normal_cdf(z_score)
        
        if bet_type == "HIGH":
            # P(Temp > Strike) = 1 - CDF
            probability = 1 - cdf_value
        else:  # LOW
            # P(Temp < Strike) = CDF
            probability = cdf_value
        
        return round(probability, 4)
    
    def apply_bias_correction(
        self,
        raw_forecast: float,
        model_bias: float
    ) -> float:
        """
        NOWBot standardı: Model bias correction
        Son 45 günün ortalama sapması tahminden düşülür
        
        Args:
            raw_forecast: Ham model tahmini
            model_bias: Modelin son 45 günlük ortalama sapması
        
        Returns:
            Bias-corrected forecast
        """
        if not config.USE_BIAS_CORRECTION:
            return raw_forecast
        
        return raw_forecast - model_bias
    
    def calculate_bet_size(
        self,
        model_probability: float,
        market_price: float,
        portfolio_capital: float,
        use_smart_pool: bool = True
    ) -> float:
        """
        Fractional Kelly criterion ile bet size hesapla
        
        Hybrid Strategy (%40 Smart Pool):
        - Günlük başlangıç sermayesinin %40'ı "İşlem Havuzu" olarak ayrılır
        - Eligible sinyaller EV büyüklüklerine göre bu havuzdan pay alır
        
        Args:
            model_probability: Modelin tahmin ettiği win probability (0-1)
            market_price: Market price (örn: 0.58 = %58 implied probability)
            portfolio_capital: Mevcut portfolio değeri
            use_smart_pool: %40 Smart Pool kullanılsın mı?
        
        Returns:
            Önerilen bet size ($)
        """
        # Decimal odds hesapla (1 / market_price)
        if market_price <= 0 or market_price >= 1:
            logger.warning(f"Invalid market price: {market_price}")
            return 0.0
        
        decimal_odds = 1 / market_price
        
        # Kelly formula: f* = (bp - q) / b
        # b = decimal_odds - 1 (net odds)
        # p = win probability
        # q = loss probability = 1 - p
        b = decimal_odds - 1
        p = model_probability
        q = 1 - p
        
        # Full Kelly
        full_kelly = (b * p - q) / b if b != 0 else 0
        
        # Negative Kelly = bahse girme
        if full_kelly <= 0:
            return 0.0
        
        # Fractional Kelly (%15)
        fractional_kelly = full_kelly * self.kelly_fraction
        
        # Smart Pool kullanılıyorsa: %40 havuz üzerinden hesapla
        if use_smart_pool:
            effective_capital = portfolio_capital * self.smart_pool_pct
        else:
            effective_capital = portfolio_capital
        
        # Dollar amount
        kelly_size = fractional_kelly * effective_capital
        
        # Hard limit: max %3 of capital (suislanchez standardı)
        max_size = portfolio_capital * self.max_bet_pct
        
        # Minimum bet size: $5
        min_size = 5.0
        
        final_size = min(kelly_size, max_size)
        final_size = max(final_size, min_size) if final_size > 0 else 0
        
        return round(final_size, 2)
    
    def calculate_edge(
        self,
        model_probability: float,
        market_price: float
    ) -> float:
        """
        Edge hesapla (model prob - implied prob)
        
        Args:
            model_probability: Model tahmini (0-1)
            market_price: Market price (0-1)
        
        Returns:
            Edge (örn: 0.07 = %7 edge)
        """
        implied_prob = market_price
        edge = model_probability - implied_prob
        return round(edge, 4)
    
    def calculate_ev(
        self,
        model_probability: float,
        market_price: float,
        stake: float = 1.0
    ) -> float:
        """
        Expected Value (EV) hesapla
        
        EV = (Win Probability * Profit) - (Loss Probability * Stake)
        
        Args:
            model_probability: Model tahmini (0-1)
            market_price: Market price (0-1)
            stake: Bet size (normalized to 1.0)
        
        Returns:
            EV per unit staked
        """
        if market_price <= 0 or market_price >= 1:
            return 0.0
        
        decimal_odds = 1 / market_price
        profit = stake * (decimal_odds - 1)
        
        p = model_probability
        q = 1 - p
        
        ev = (p * profit) - (q * stake)
        
        # Normalize per unit
        ev_normalized = ev / stake if stake > 0 else 0
        
        return round(ev_normalized, 4)
    
    def analyze_signal(
        self,
        model_probability: float,
        market_price: float,
        portfolio_capital: float,
        current_exposure: float,
        city_bets_count: int,
        region_exposure: float
    ) -> Dict:
        """
        Komple sinyal analizi
        
        Returns:
            Signal analysis result dictionary
        """
        # Temel metrikleri hesapla
        edge = self.calculate_edge(model_probability, market_price)
        ev = self.calculate_ev(model_probability, market_price)
        recommended_size = self.calculate_bet_size(
            model_probability, 
            market_price, 
            portfolio_capital
        )
        
        # Risk kontrolleri
        risk_checks = {
            'edge_ok': edge >= self.edge_threshold,
            'ev_positive': ev > 0,
            'city_limit_ok': city_bets_count < config.MAX_BETS_PER_CITY,
            'exposure_ok': self._check_exposure(
                current_exposure, 
                recommended_size, 
                portfolio_capital
            ),
            'region_ok': self._check_region_exposure(
                region_exposure, 
                recommended_size, 
                portfolio_capital
            )
        }
        
        # Karar ver
        should_bet = all(risk_checks.values())
        
        # Reddedilme nedeni
        reject_reason = None
        if not should_bet:
            reasons = []
            if not risk_checks['edge_ok']:
                reasons.append(f"Edge {edge:.2%} < threshold {self.edge_threshold:.2%}")
            if not risk_checks['ev_positive']:
                reasons.append(f"EV {ev:.4f} <= 0")
            if not risk_checks['city_limit_ok']:
                reasons.append(f"City bet limit reached ({city_bets_count}/{config.MAX_BETS_PER_CITY})")
            if not risk_checks['exposure_ok']:
                reasons.append("Total exposure limit exceeded")
            if not risk_checks['region_ok']:
                reasons.append("Regional exposure limit exceeded")
            reject_reason = "; ".join(reasons)
        
        return {
            'model_probability': model_probability,
            'market_price': market_price,
            'edge': edge,
            'ev': ev,
            'recommended_size': recommended_size,
            'risk_checks': risk_checks,
            'should_bet': should_bet,
            'reject_reason': reject_reason,
            'confidence': self._calculate_confidence(model_probability, edge, ev)
        }
    
    def _check_exposure(
        self,
        current_exposure: float,
        new_bet: float,
        capital: float
    ) -> bool:
        """Toplam exposure limiti kontrolü"""
        max_exposure = capital * config.TOTAL_EXPOSURE_PCT
        return (current_exposure + new_bet) <= max_exposure
    
    def _check_region_exposure(
        self,
        region_exposure: float,
        new_bet: float,
        capital: float
    ) -> bool:
        """Bölgesel exposure kontrolü"""
        max_region = capital * config.MAX_REGIONAL_EXPOSURE_PCT
        return (region_exposure + new_bet) <= max_region
    
    def _calculate_confidence(
        self,
        probability: float,
        edge: float,
        ev: float
    ) -> float:
        """
        Sinyal confidence skoru hesapla (0-1)
        
        Higher edge + higher EV + probability far from 0.5 = higher confidence
        """
        # Edge component (max 0.4)
        edge_score = min(edge / 0.10, 1.0) * 0.4
        
        # EV component (max 0.3)
        ev_score = min(ev / 0.20, 1.0) * 0.3
        
        # Probability certainty component (max 0.3)
        # Probability ne kadar 0 veya 1'e yakınsa o kadar yüksek
        prob_certainty = abs(probability - 0.5) * 2
        prob_score = prob_certainty * 0.3
        
        confidence = edge_score + ev_score + prob_score
        return round(min(confidence, 1.0), 4)
    
    def should_open_bet(
        self,
        signal: Dict,
        portfolio: Dict
    ) -> bool:
        """
        Bahis açılmalı mı kontrol et
        
        Args:
            signal: Signal analysis result
            portfolio: Portfolio dict
        
        Returns:
            True/False
        """
        if not signal.get('should_bet', False):
            return False
        
        # Ekstra portfolio kontrolleri
        daily_pnl = portfolio.get('daily_pnl', 0)
        capital = portfolio.get('current_capital', portfolio.get('starting_capital', 1000))
        
        # Günlük kayıp limiti
        if daily_pnl <= -capital * config.DAILY_LOSS_LIMIT:
            logger.warning("Daily loss limit hit - no new bets")
            return False
        
        return True


# Singleton instance
betting_engine = BettingEngine()
