"""
Settlement Engine - Paper Mode Settlement
Gerçek API çağrısı YOK, sadece DB'de PnL hesapla
"""
import logging
from typing import Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class SettlementEngine:
    """Paper trading settlement engine"""
    
    def __init__(self, db):
        self.db = db
    
    async def check_settlements(self) -> Dict:
        """
        Tüm açık bahislerin settlement durumunu kontrol et
        
        Returns:
            Settlement results dictionary
        """
        open_bets = self.db.get_all_open_bets()
        
        if not open_bets:
            return {'settled': 0, 'pending': 0, 'results': []}
        
        results = []
        settled_count = 0
        
        for bet in open_bets:
            # Paper mode: Simulated settlement
            # Gerçek bot'ta burada Polymarket API'den sonuç çekilir
            result = await self._simulate_settlement(bet)
            
            if result and result.get('settled'):
                settled_count += 1
                
                # PnL hesapla
                pnl = self._calculate_pnl(
                    bet['side'],
                    result['outcome'],
                    bet['entry_price'],
                    bet['size']
                )
                
                # Bahsi kapat ve PnL kaydet
                self.db.close_bet(
                    bet['condition_id'],
                    pnl,
                    result['outcome']
                )
                
                results.append({
                    'condition_id': bet['condition_id'],
                    'city': bet['city'],
                    'side': bet['side'],
                    'result': result['outcome'],
                    'pnl': pnl,
                    'settled': True
                })
                
                logger.info(f"Settled: {bet['condition_id']} - {bet['city']} - PnL: ${pnl:.2f}")
        
        pending_count = len(open_bets) - settled_count
        
        return {
            'settled': settled_count,
            'pending': pending_count,
            'results': results
        }
    
    async def _simulate_settlement(self, bet: Dict) -> Optional[Dict]:
        """
        Paper mode için simüle edilmiş settlement
        
        NOT: Gerçek bot'ta Polymarket API'den gerçek sonuç çekilir.
        Paper mode'da test için random settlement kullanıyoruz.
        
        Args:
            bet: Open bet dictionary
        
        Returns:
            Settlement result veya None (henüz çözülmemiş)
        """
        import random
        
        # Paper mode simülasyonu:
        # - Model probability'ye weighted random ile sonuç üret
        # - Gerçek bot'ta: await polymarket_client.get_result(condition_id)
        
        model_prob = bet.get('model_probability', 0.5)
        
        # Weighted random outcome
        # Model %60 YES diyorsa, %60 ihtimalle YES çıksın
        outcome = "YES" if random.random() < model_prob else "NO"
        
        # Simüle edilmiş settlement date (bet oluşturulduktan 1-3 gün sonra)
        from datetime import timedelta
        created_at = datetime.fromisoformat(bet['created_at'].replace('Z', '+00:00'))
        settlement_date = created_at + timedelta(days=random.randint(1, 3))
        
        # Henüz settlement zamanı gelmiş mi?
        if datetime.now() < settlement_date:
            return None  # Henüz çözülmemiş
        
        return {
            'outcome': outcome,
            'settled': True,
            'settlement_date': settlement_date.isoformat(),
            'simulated': True  # Paper mode flag
        }
    
    def _calculate_pnl(
        self,
        bet_side: str,
        outcome: str,
        entry_price: float,
        size: float
    ) -> float:
        """
        PnL hesapla
        
        Args:
            bet_side: "YES" veya "NO"
            outcome: "YES" veya "NO" (gerçekleşen sonuç)
            entry_price: Giriş fiyatı
            size: Bahis tutarı ($)
        
        Returns:
            PnL ($) - Pozitif=kazanç, Negatif=kayıp
        """
        if bet_side == outcome:
            # Kazandı
            # Shares = size / entry_price
            # Payout = shares * $1
            # PnL = payout - size
            shares = size / entry_price
            payout = shares * 1.0  # Her share $1 öder
            pnl = payout - size
        else:
            # Kaybetti - tüm bahsi kaybeder
            pnl = -size
        
        return round(pnl, 2)
    
    async def settle_specific_bet(
        self,
        condition_id: str,
        outcome: str
    ) -> Dict:
        """
        Belirli bir bahsi manuel olarak settle et
        
        Args:
            condition_id: Condition ID
            outcome: "YES" veya "NO"
        
        Returns:
            Settlement result
        """
        # Open bet bul
        open_bets = self.db.get_all_open_bets()
        bet = next((b for b in open_bets if b['condition_id'] == condition_id), None)
        
        if not bet:
            return {
                'success': False,
                'error': f'Bet not found: {condition_id}'
            }
        
        # PnL hesapla
        pnl = self._calculate_pnl(
            bet['side'],
            outcome,
            bet['entry_price'],
            bet['size']
        )
        
        # Bahsi kapat
        self.db.close_bet(condition_id, pnl, outcome)
        
        logger.info(f"Manual settlement: {condition_id} - PnL: ${pnl:.2f}")
        
        return {
            'success': True,
            'condition_id': condition_id,
            'side': bet['side'],
            'outcome': outcome,
            'pnl': pnl
        }
    
    def get_settlement_history(self, limit: int = 50) -> list:
        """
        Settlement geçmişini getir
        
        Args:
            limit: Max records
        
        Returns:
            List of settled bets
        """
        return self.db.get_closed_bets(limit)
    
    def get_settlement_stats(self) -> Dict:
        """
        Settlement istatistikleri
        
        Returns:
            Statistics dictionary
        """
        closed_bets = self.db.get_closed_bets(limit=1000)
        
        if not closed_bets:
            return {
                'total_bets': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_pnl': 0.0,
                'best_bet': None,
                'worst_bet': None
            }
        
        wins = [b for b in closed_bets if b['pnl'] > 0]
        losses = [b for b in closed_bets if b['pnl'] <= 0]
        
        total_pnl = sum(b['pnl'] for b in closed_bets)
        avg_pnl = total_pnl / len(closed_bets)
        
        best_bet = max(closed_bets, key=lambda x: x['pnl'])
        worst_bet = min(closed_bets, key=lambda x: x['pnl'])
        
        return {
            'total_bets': len(closed_bets),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': round(len(wins) / len(closed_bets) * 100, 2),
            'total_pnl': round(total_pnl, 2),
            'avg_pnl': round(avg_pnl, 2),
            'best_bet': {
                'city': best_bet['city'],
                'side': best_bet['side'],
                'pnl': best_bet['pnl']
            },
            'worst_bet': {
                'city': worst_bet['city'],
                'side': worst_bet['side'],
                'pnl': worst_bet['pnl']
            }
        }


# Factory function
def create_settlement_engine(db):
    return SettlementEngine(db)
