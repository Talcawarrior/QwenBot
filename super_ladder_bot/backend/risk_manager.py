"""
Risk Manager - Circuit Breakers ve Risk Kontrolleri
Günlük stop-loss, şehir bazlı limit, korelasyon koruması
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from config import config

logger = logging.getLogger(__name__)


class RiskManager:
    """Risk yönetimi ve circuit breaker sistemi"""
    
    def __init__(self, db):
        self.db = db
        self.daily_loss_limit = config.DAILY_LOSS_LIMIT
        self.max_bets_per_city = config.MAX_BETS_PER_CITY
        self.total_exposure_pct = config.TOTAL_EXPOSURE_PCT
        self.max_regional_exposure_pct = config.MAX_REGIONAL_EXPOSURE_PCT
        self.is_stopped = False  # Bot durduruldu mu?
        self.stop_reason: Optional[str] = None
    
    def check_all_risks(self, portfolio: Dict) -> Dict:
        """
        Tüm risk kontrollerini yap
        
        Returns:
            Risk check results dictionary
        """
        checks = {
            'daily_loss': self.check_daily_loss(portfolio),
            'total_exposure': self.check_total_exposure(portfolio),
            'city_limits': self.check_city_limits(),
            'regional_exposure': self.check_regional_exposure(),
            'is_stopped': self.is_stopped,
            'stop_reason': self.stop_reason
        }
        
        # Herhangi bir kritik kontrol başarısızsa botu durdur
        critical_failures = [
            checks['daily_loss']['hit'],
        ]
        
        if any(critical_failures) and not self.is_stopped:
            self.trigger_circuit_breaker("Critical risk limit hit")
        
        return checks
    
    def check_daily_loss(self, portfolio: Dict) -> Dict:
        """
        Günlük stop-loss kontrolü
        
        Returns:
            Check result dictionary
        """
        capital = portfolio.get('current_capital', portfolio.get('starting_capital', 1000))
        daily_pnl = portfolio.get('daily_pnl', 0)
        daily_loss_pct = abs(daily_pnl) / capital if daily_pnl < 0 else 0
        
        hit = daily_pnl <= -capital * self.daily_loss_limit
        
        result = {
            'hit': hit,
            'daily_pnl': daily_pnl,
            'daily_pnl_pct': round((daily_pnl / capital) * 100, 2) if capital > 0 else 0,
            'limit_pct': self.daily_loss_limit * 100,
            'remaining_before_stop': round(capital * self.daily_loss_limit + daily_pnl, 2) if daily_pnl < 0 else None,
            'status': 'CRITICAL' if hit else ('WARNING' if daily_loss_pct > self.daily_loss_limit * 0.8 else 'OK')
        }
        
        if hit:
            logger.critical(f"DAILY LOSS LIMIT HIT! PnL: {daily_pnl:.2f} ({daily_loss_pct:.2%})")
        
        return result
    
    def check_total_exposure(self, portfolio: Dict) -> Dict:
        """
        Toplam exposure kontrolü
        
        Returns:
            Check result dictionary
        """
        capital = portfolio.get('current_capital', portfolio.get('starting_capital', 1000))
        current_exposure = self.db.get_open_exposure()
        max_exposure = capital * self.total_exposure_pct
        exposure_pct = current_exposure / capital if capital > 0 else 0
        
        result = {
            'current_exposure': round(current_exposure, 2),
            'max_exposure': round(max_exposure, 2),
            'exposure_pct': round(exposure_pct * 100, 2),
            'limit_pct': self.total_exposure_pct * 100,
            'remaining': round(max_exposure - current_exposure, 2),
            'status': 'WARNING' if exposure_pct > self.total_exposure_pct * 0.9 else 'OK'
        }
        
        return result
    
    def check_city_limits(self) -> Dict:
        """
        Şehir bazlı bet limit kontrolü
        
        Returns:
            City limits dictionary
        """
        city_limits = {}
        warnings = []
        
        for city in config.CITIES:
            city_name = city['name']
            bet_count = self.db.get_open_bets_count(city_name)
            
            city_limits[city_name] = {
                'count': bet_count,
                'limit': self.max_bets_per_city,
                'remaining': self.max_bets_per_city - bet_count,
                'at_limit': bet_count >= self.max_bets_per_city
            }
            
            if bet_count >= self.max_bets_per_city:
                warnings.append(f"{city_name}: {bet_count}/{self.max_bets_per_city} bets")
        
        at_limit_cities = [c for c, data in city_limits.items() if data['at_limit']]
        
        return {
            'cities': city_limits,
            'at_limit': at_limit_cities,
            'warnings': warnings,
            'status': 'WARNING' if at_limit_cities else 'OK'
        }
    
    def check_regional_exposure(self) -> Dict:
        """
        Bölgesel exposure kontrolü (korelasyon koruması)
        
        Returns:
            Regional exposure dictionary
        """
        regions = set(city.get('region', 'Unknown') for city in config.CITIES)
        regional_data = {}
        warnings = []
        
        capital = self.db.get_portfolio()
        capital = capital.get('current_capital', capital.get('starting_capital', 1000)) if capital else 1000
        max_regional = capital * self.max_regional_exposure_pct
        
        for region in regions:
            exposure = self.db.get_region_exposure(region)
            exposure_pct = exposure / capital if capital > 0 else 0
            
            regional_data[region] = {
                'exposure': round(exposure, 2),
                'max_exposure': round(max_regional, 2),
                'exposure_pct': round(exposure_pct * 100, 2),
                'limit_pct': self.max_regional_exposure_pct * 100,
                'remaining': round(max_regional - exposure, 2),
                'status': 'WARNING' if exposure_pct > self.max_regional_exposure_pct * 0.9 else 'OK'
            }
            
            if exposure_pct > self.max_regional_exposure_pct * 0.9:
                warnings.append(f"{region}: {exposure_pct:.1%} regional exposure")
        
        return {
            'regions': regional_data,
            'warnings': warnings,
            'status': 'WARNING' if warnings else 'OK'
        }
    
    def can_place_bet(
        self,
        city: str,
        size: float,
        portfolio: Dict
    ) -> Dict:
        """
        Yeni bahis konulabilir mi kontrol et
        
        Args:
            city: Şehir adı
            size: Bahis tutarı
            portfolio: Portfolio dict
        
        Returns:
            Permission result dictionary
        """
        # Bot durdurulmuş mu?
        if self.is_stopped:
            return {
                'allowed': False,
                'reason': f"Bot stopped: {self.stop_reason}"
            }
        
        # Günlük kayıp limiti
        daily_loss_check = self.check_daily_loss(portfolio)
        if daily_loss_check['hit']:
            return {
                'allowed': False,
                'reason': "Daily loss limit hit"
            }
        
        # Şehir limiti
        city_bet_count = self.db.get_open_bets_count(city)
        if city_bet_count >= self.max_bets_per_city:
            return {
                'allowed': False,
                'reason': f"City bet limit reached ({city_bet_count}/{self.max_bets_per_city})"
            }
        
        # Toplam exposure
        current_exposure = self.db.get_open_exposure()
        capital = portfolio.get('current_capital', portfolio.get('starting_capital', 1000))
        max_exposure = capital * self.total_exposure_pct
        
        if current_exposure + size > max_exposure:
            return {
                'allowed': False,
                'reason': f"Total exposure limit ({max_exposure:.2f}) would be exceeded"
            }
        
        # Bölgesel exposure
        city_info = config.get_city_by_name(city)
        if city_info:
            region = city_info.get('region', 'Unknown')
            region_exposure = self.db.get_region_exposure(region)
            max_regional = capital * self.max_regional_exposure_pct
            
            if region_exposure + size > max_regional:
                return {
                    'allowed': False,
                    'reason': f"Regional exposure limit for {region} would be exceeded"
                }
        
        return {
            'allowed': True,
            'reason': "All checks passed"
        }
    
    def trigger_circuit_breaker(self, reason: str):
        """
        Circuit breaker tetikle - botu durdur
        
        Args:
            reason: Durdurma nedeni
        """
        self.is_stopped = True
        self.stop_reason = reason
        logger.critical(f"CIRCUIT BREAKER TRIGGERED: {reason}")
    
    def reset_circuit_breaker(self):
        """Circuit breaker'ı sıfırla - botu yeniden başlat"""
        self.is_stopped = False
        self.stop_reason = None
        logger.info("Circuit breaker reset - bot resumed")
    
    def get_risk_summary(self, portfolio: Dict) -> Dict:
        """
        Özet risk raporu
        
        Returns:
            Risk summary dictionary
        """
        all_checks = self.check_all_risks(portfolio)
        
        # Genel durum
        critical_issues = []
        warnings = []
        
        if all_checks['daily_loss']['hit']:
            critical_issues.append("Daily loss limit hit")
        
        if all_checks['total_exposure']['status'] == 'WARNING':
            warnings.append("High total exposure")
        
        if all_checks['city_limits']['status'] == 'WARNING':
            warnings.extend(all_checks['city_limits']['warnings'])
        
        if all_checks['regional_exposure']['status'] == 'WARNING':
            warnings.extend(all_checks['regional_exposure']['warnings'])
        
        return {
            'status': 'CRITICAL' if critical_issues else ('WARNING' if warnings else 'OK'),
            'is_stopped': self.is_stopped,
            'stop_reason': self.stop_reason,
            'critical_issues': critical_issues,
            'warnings': warnings,
            'checks': all_checks,
            'timestamp': datetime.now().isoformat()
        }
    
    def should_reset_daily(self) -> bool:
        """
        Günlük PnL sıfırlama zamanı mı? (yeni gün)
        
        Returns:
            True/False
        """
        portfolio = self.db.get_portfolio()
        if not portfolio:
            return False
        
        last_reset = portfolio.get('last_reset_at')
        if not last_reset:
            return True
        
        try:
            last_reset_dt = datetime.fromisoformat(last_reset.replace('Z', '+00:00'))
            now = datetime.now()
            
            # Farklı gün mü?
            return last_reset_dt.date() < now.date()
        except:
            return False
    
    def auto_reset_daily(self):
        """Günlük PnL otomatik sıfırlama"""
        if self.should_reset_daily():
            logger.info("Auto-resetting daily PnL for new day")
            self.db.reset_daily_pnl()
            
            # Circuit breaker'ı da sıfırla (yeni gün)
            if self.is_stopped and 'daily' in self.stop_reason.lower():
                self.reset_circuit_breaker()
            
            return True
        return False


# Factory function
def create_risk_manager(db) -> RiskManager:
    return RiskManager(db)
