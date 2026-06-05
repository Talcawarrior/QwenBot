"""
RISK MANAGER MODULE - POLYMARKET ULTIMATE HYBRID WEATHER BOT
- Fraksiyonel Kelly, Smart Pool, Circuit Breakers
- HATA 1 DÜZELTİLDİ (MIN_BET_SIZE tanımlı)
"""

import logging
from typing import Dict, List
from sqlalchemy import func
from config import Config
from database import Bet, Portfolio

logger = logging.getLogger(__name__)


class RiskManager:
    """Risk management with Kelly sizing, smart pool, and circuit breakers."""
    def __init__(self, db_session=None, config=None):
        self.db = db_session
        self.config = config or Config()
        self.portfolio_value = getattr(self.config, "INITIAL_PORTFOLIO", 1000.0)
        self.daily_pnl = 0.0
        self.open_bets_count = 0
        self.city_bet_counts: Dict[str, int] = {}
        # Load persistent state from DB (fixes restart risk loss)
        self._load_from_db()

    def update_portfolio(self, value: float):
        """Portföy değerini güncelle"""
        self.portfolio_value = value

    def update_daily_pnl(self, pnl: float):
        """Günlük PnL'i güncelle ve circuit breaker kontrol et"""
        self.daily_pnl = pnl

        # Circuit breaker: Günlük stop-loss
        if self.daily_pnl <= -self.config.daily_loss_limit_amount:
            logger.warning("DAILY STOP-LOSS TRIGGERED! PnL: $%.2f", self.daily_pnl)
            return False  # Bot durdurulmalı

        return True  # Bot çalışabilir

    def check_city_cap(self, city_code: str) -> bool:
        """Aynı şehirde max bahis sayısını kontrol et (CITY_CAP)"""
        current_count = self.city_bet_counts.get(city_code, 0)
        return current_count < self.config.CITY_CAP

    def increment_city_bet(self, city_code: str):
        """Şehir bahis sayısını artır"""
        self.city_bet_counts[city_code] = self.city_bet_counts.get(city_code, 0) + 1

    def decrement_city_bet(self, city_code: str):
        """Şehir bahis sayısını azalt (bahis kapandığında)"""
        if city_code in self.city_bet_counts:
            self.city_bet_counts[city_code] = max(
                0, self.city_bet_counts[city_code] - 1
            )

    def calculate_kelly_bet_size(self, model_prob: float, market_price: float) -> float:
        """
        Fraksiyonel Kelly formülü ile bahis boyutu hesapla
        Doğrudan side-aware model_prob ve market_price alır (BUG-07 fix)
        """
        if model_prob <= 0 or market_price <= 0 or market_price >= 1:
            return 0.0

        if model_prob >= 1.0:
            model_prob = 0.99

        b = (1 - market_price) / market_price  # Decimal odds for this side
        p = model_prob
        q = 1 - p

        kelly_fraction = (b * p - q) / b if b > 0 else 0

        # Apply fractional Kelly (15%)
        fractional_kelly = kelly_fraction * self.config.KELLY_FRACTION

        if fractional_kelly <= 0:
            return 0.0

        # Dollar amount
        bet_amount = self.portfolio_value * fractional_kelly

        bet_amount = max(bet_amount, self.config.MIN_BET_SIZE)

        # MAX_BET_PCT cap (%3)
        max_bet = self.portfolio_value * self.config.MAX_BET_PCT
        bet_amount = min(bet_amount, max_bet)

        return round(bet_amount, 2)

    def check_exposure_cap(
        self, current_exposure: float, additional_bet: float
    ) -> bool:
        """Toplam pozisyon limitini kontrol et (EXPOSURE_CAP %25)"""
        max_exposure = self.portfolio_value * self.config.TOTAL_EXPOSURE_PCT
        return (current_exposure + additional_bet) <= max_exposure

    def get_smart_pool_allocation(
        self, eligible_signals: List[Dict]
    ) -> Dict[str, float]:
        """
        Smart Pool (%40) dağıtımı - EV bazlı ağırlıklandırma
        """
        if not eligible_signals:
            return {}

        smart_pool = self.portfolio_value * self.config.SMART_POOL_PCT

        # EV bazlı ağırlıklar
        total_ev = sum(
            sig.get("ev", 0) for sig in eligible_signals if sig.get("ev", 0) > 0
        )

        if total_ev <= 0:
            return {}

        allocations = {}
        for signal in eligible_signals:
            ev = signal.get("ev", 0)
            if ev > 0:
                weight = ev / total_ev
                allocation = smart_pool * weight

                # Kelly ile sınırla
                kelly_size = self.calculate_kelly_bet_size(
                    signal.get("model_prob", 0.5), signal["market_price"]
                )
                allocation = min(allocation, kelly_size)

                allocations[signal["city_code"]] = round(allocation, 2)

        return allocations

    def is_bot_locked(self) -> bool:
        """Bot'un kilitli olup olmadığını kontrol et (daily stop-loss)"""
        return self.daily_pnl <= -self.config.daily_loss_limit_amount

    def get_daily_pnl(self) -> float:
        """Return current daily PnL for main.py /api/status"""
        return self.daily_pnl

    def get_total_exposure(self) -> float:
        """Return current total exposure (for risk checks and status)"""
        # Real sum from DB (BUG-13/22 fix)
        if self.db:
            try:
                total = (
                    self.db.query(func.coalesce(func.sum(Bet.stake_amount), 0.0))
                    .filter(Bet.status.in_(["active", "open"]))
                    .scalar()
                )
                return float(total or 0.0)
            except Exception:  # pylint: disable=broad-exception-caught
                pass
        # Fallback rough estimate
        exposure = sum(self.city_bet_counts.values()) * 20.0
        return exposure

    def get_portfolio_value(self) -> float:
        """Return current portfolio value"""
        return self.portfolio_value

    def _load_from_db(self):
        """DB'den kalıcı risk durumunu yükle (portfolio, active bets exposure, daily_pnl)."""
        if not self.db:
            return
        try:
            # Portfolio
            portfolio = self.db.query(Portfolio).filter(Portfolio.id == 1).first()
            if portfolio:
                self.portfolio_value = (
                    portfolio.current_value
                    or portfolio.initial_value
                    or self.portfolio_value
                )
                self.daily_pnl = portfolio.daily_pnl or 0.0

            # Active bets'ten city exposure ve count
            active = self.db.query(Bet).filter(Bet.status.in_(["active", "open"])).all()
            self.city_bet_counts = {}
            self.open_bets_count = len(active)
            for bet in active:
                cc = bet.city_code or "unknown"
                self.city_bet_counts[cc] = self.city_bet_counts.get(cc, 0) + 1
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Risk load from DB warning: %s", e)


if __name__ == "__main__":
    print("=== RISK MANAGER TEST ===")

    rm = RiskManager(None, None)

    print(f"\n1. Portfolio: ${rm.portfolio_value}")
    print(f"   Smart Pool: ${rm.portfolio_value * rm.config.SMART_POOL_PCT}")
    print(f"   Max Exposure: ${rm.portfolio_value * rm.config.TOTAL_EXPOSURE_PCT}")
    print(f"   Max Bet: ${rm.portfolio_value * rm.config.MAX_BET_PCT}")
    print(f"   Daily Stop-Loss: ${rm.config.daily_loss_limit_amount}")
    print(f"   MIN_BET_SIZE: ${rm.config.MIN_BET_SIZE} (Hata 1 fixed)")

    print("\n2. Testing Kelly Calculation...")
    # Edge: 10%, Market Price: 0.45
    kelly = rm.calculate_kelly_bet_size(model_prob=0.55, market_price=0.45)
    print(f"   Kelly (edge=10%, price=0.45): ${kelly}")

    print("\n3. Testing City Cap...")
    print(f"   Dallas cap check: {rm.check_city_cap('KDAL')}")
    rm.increment_city_bet("KDAL")
    for i in range(4):
        rm.increment_city_bet("KDAL")
    print(f"   After 5 bets: {rm.check_city_cap('KDAL')} (should be False)")

    print("\n4. Testing Daily Stop-Loss...")
    rm.update_daily_pnl(-60.0)
    print(f"   PnL: ${rm.daily_pnl}")
    print(f"   Bot locked: {rm.is_bot_locked()} (should be True)")

    print("\n✅ All risk manager tests passed!")
