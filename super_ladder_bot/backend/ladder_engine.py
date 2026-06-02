"""
Ladder Engine - Kademeli Limit Emir Sistemi
Toplam tutarı 4 kademeli limit emirlere böler
Maker fee = 0 avantajını kullanır
"""
import logging
from typing import List, Dict
from config import config

logger = logging.getLogger(__name__)


class LadderEngine:
    """Order ladder calculator ve manager"""
    
    def __init__(self):
        self.levels = config.LADDER_LEVELS
        self.weights = config.LADDER_WEIGHTS
        self.price_step = config.PRICE_STEP
    
    def calculate_order_ladder(
        self,
        total_size: float,
        target_price: float,
        side: str = "BUY"
    ) -> List[Dict]:
        """
        Toplam tutarı kademeli limit emirlere böl
        
        Args:
            total_size: Toplam bet size ($)
            target_price: Hedef market price (örn: 0.58)
            side: "BUY" veya "SELL"
        
        Returns:
            Ladder orders listesi
        """
        ladder = []
        
        for i in range(self.levels):
            # Her kademe için fiyat adımı (0.01, 0.02, 0.03, 0.04)
            price_offset = self.price_step * (i + 1)
            
            if side == "BUY":
                # Alım için hedef fiyatın altına kademeler
                order_price = max(0.01, target_price - price_offset)
            else:
                # Satış için hedef fiyatın üstüne kademeler
                order_price = min(0.99, target_price + price_offset)
            
            # Her kademe için boyut (weight ile çarp)
            order_size = total_size * self.weights[i]
            
            ladder.append({
                "level": i + 1,
                "price": round(order_price, 2),
                "size": round(order_size, 2),
                "side": side,
                "orderType": "GTC",  # Good Till Cancel
                "filled_size": 0.0,
                "status": "pending"
            })
        
        logger.info(f"Ladder calculated: {len(ladder)} levels, total_size={total_size}, target_price={target_price}")
        return ladder
    
    def calculate_total_filled(
        self,
        ladder: List[Dict],
        current_market_price: float,
        side: str = "BUY"
    ) -> Dict:
        """
        Mevcut market fiyatında ne kadar dolduğunu hesapla
        Paper mode simülasyonu için
        
        Args:
            ladder: Ladder orders listesi
            current_market_price: Şu anki market price
            side: "BUY" veya "SELL"
        
        Returns:
            Filled amount ve average price
        """
        total_filled = 0.0
        total_cost = 0.0
        
        for order in ladder:
            if side == "BUY":
                # Alım emri: market price <= order price ise dolar
                if current_market_price <= order['price']:
                    filled = order['size'] - order.get('filled_size', 0)
                    total_filled += filled
                    total_cost += filled * order['price']
            else:
                # Satım emri: market price >= order price ise dolar
                if current_market_price >= order['price']:
                    filled = order['size'] - order.get('filled_size', 0)
                    total_filled += filled
                    total_cost += filled * order['price']
        
        avg_price = total_cost / total_filled if total_filled > 0 else 0.0
        
        return {
            "total_filled": round(total_filled, 2),
            "avg_price": round(avg_price, 2),
            "total_cost": round(total_cost, 2)
        }
    
    def update_ladder_status(
        self,
        ladder: List[Dict],
        current_market_price: float,
        side: str = "BUY"
    ) -> List[Dict]:
        """
        Ladder durumunu güncelle (hangi emirler doldu)
        
        Returns:
            Güncellenmiş ladder listesi
        """
        updated_ladder = []
        
        for order in ladder:
            order_copy = order.copy()
            
            if side == "BUY":
                if current_market_price <= order['price']:
                    order_copy['status'] = 'filled'
                    order_copy['filled_size'] = order['size']
                elif current_market_price <= order['price'] + 0.02:
                    # Fiyat yaklaşıyor - partial fill simülasyonu
                    order_copy['status'] = 'partial'
                    order_copy['filled_size'] = order['size'] * 0.3
                else:
                    order_copy['status'] = 'pending'
            else:
                if current_market_price >= order['price']:
                    order_copy['status'] = 'filled'
                    order_copy['filled_size'] = order['size']
                elif current_market_price >= order['price'] - 0.02:
                    order_copy['status'] = 'partial'
                    order_copy['filled_size'] = order['size'] * 0.3
                else:
                    order_copy['status'] = 'pending'
            
            updated_ladder.append(order_copy)
        
        return updated_ladder
    
    def get_ladder_summary(self, ladder: List[Dict]) -> Dict:
        """
        Ladder özeti çıkar
        
        Returns:
            Ladder summary dictionary
        """
        total_size = sum(order['size'] for order in ladder)
        total_filled = sum(order.get('filled_size', 0) for order in ladder)
        
        pending_orders = [o for o in ladder if o['status'] == 'pending']
        filled_orders = [o for o in ladder if o['status'] == 'filled']
        partial_orders = [o for o in ladder if o['status'] == 'partial']
        
        avg_price = 0.0
        if filled_orders or partial_orders:
            filled_cost = sum(
                o.get('filled_size', 0) * o['price'] 
                for o in ladder
            )
            avg_price = filled_cost / total_filled if total_filled > 0 else 0.0
        
        return {
            "total_size": round(total_size, 2),
            "total_filled": round(total_filled, 2),
            "fill_pct": round((total_filled / total_size) * 100, 2) if total_size > 0 else 0,
            "avg_price": round(avg_price, 2),
            "pending_count": len(pending_orders),
            "filled_count": len(filled_orders),
            "partial_count": len(partial_orders),
            "levels": [
                {
                    "level": o['level'],
                    "price": o['price'],
                    "size": o['size'],
                    "filled": o.get('filled_size', 0),
                    "status": o['status']
                }
                for o in ladder
            ]
        }
    
    def cancel_ladder(self, ladder: List[Dict]) -> List[Dict]:
        """Tüm emirleri iptal et"""
        for order in ladder:
            order['status'] = 'cancelled'
            order['filled_size'] = 0.0
        return ladder
    
    def adjust_ladder_for_partial_fill(
        self,
        ladder: List[Dict],
        filled_amount: float
    ) -> List[Dict]:
        """
        Kısmi dolum sonrası kalan tutarı yeniden dağıt
        
        Args:
            ladder: Orijinal ladder
            filled_amount: Dolan miktar
        
        Returns:
            Güncellenmiş ladder (kalan tutar için)
        """
        total_original = sum(order['size'] for order in ladder)
        remaining = total_original - filled_amount
        
        if remaining <= 0:
            return self.cancel_ladder(ladder)
        
        # Kalan tutarı pending emirlere yeniden dağıt
        pending_orders = [o for o in ladder if o['status'] == 'pending']
        
        if not pending_orders:
            return ladder
        
        # Proportional redistribution
        for order in ladder:
            if order['status'] == 'pending':
                new_size = (order['size'] / total_original) * remaining
                order['size'] = round(new_size, 2)
        
        return ladder


# Singleton instance
ladder_engine = LadderEngine()
