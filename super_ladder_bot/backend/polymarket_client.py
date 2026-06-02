"""
Polymarket Client - Gamma API (Read-Only)
Paper Trading Edition - Gerçek işlem YOK, sadece veri okuma
"""
import aiohttp
import logging
from typing import Dict, List, Optional
from config import config

logger = logging.getLogger(__name__)


class PolymarketClient:
    """
    Polymarket Gamma API client
    Sadece read-only işlemler için (paper trading)
    """
    
    def __init__(self):
        self.base_url = config.POLYMARKET_GAMMA_API
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def start(self):
        """HTTP session başlat"""
        self.session = aiohttp.ClientSession()
        logger.info("Polymarket client started")
    
    async def stop(self):
        """HTTP session kapat"""
        if self.session:
            await self.session.close()
            logger.info("Polymarket client stopped")
    
    async def get_temperature_events(self) -> List[Dict]:
        """
        Tüm daily-temperature pazarlarını çek
        
        Returns:
            Events listesi
        """
        if not self.session:
            await self.start()
        
        url = f"{self.base_url}/events"
        params = {
            "tag_slug": "daily-temperature",
            "limit": 500,
            "closed": "false"
        }
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    events = data.get('results', [])
                    logger.info(f"Fetched {len(events)} temperature events")
                    return events
                else:
                    logger.error(f"API error: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Fetch events error: {e}")
            return []
    
    async def get_event_details(self, event_id: str) -> Optional[Dict]:
        """
        Event detaylarını getir
        
        Args:
            event_id: Event ID
        
        Returns:
            Event details dictionary
        """
        if not self.session:
            await self.start()
        
        url = f"{self.base_url}/events/{event_id}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.error(f"Event details error: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Fetch event details error: {e}")
            return None
    
    async def get_market_prices(self, condition_id: str) -> Dict:
        """
        YES/NO fiyatlarını getir
        
        Args:
            condition_id: Condition ID
        
        Returns:
            Price dictionary {yes: float, no: float}
        """
        if not self.session:
            await self.start()
        
        url = f"{self.base_url}/conditions/{condition_id}/prices"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Fiyatları parse et
                    prices = {}
                    for outcome in data.get('outcomes', []):
                        side = outcome.get('outcome', '').upper()
                        price = outcome.get('price', 0.5)
                        prices[side] = price
                    
                    return {
                        'yes': prices.get('YES', 0.5),
                        'no': prices.get('NO', 0.5),
                        'spread': abs(prices.get('YES', 0.5) - prices.get('NO', 0.5))
                    }
                else:
                    logger.error(f"Market prices error: {response.status}")
                    return {'yes': 0.5, 'no': 0.5, 'spread': 0}
        except Exception as e:
            logger.error(f"Fetch market prices error: {e}")
            return {'yes': 0.5, 'no': 0.5, 'spread': 0}
    
    def parse_event_data(self, event: Dict) -> Optional[Dict]:
        """
        Event verisini parse et
        
        Returns:
            Parsed event dictionary
        """
        try:
            title = event.get('title', '')
            
            # Şehir adını çıkar
            city = self._extract_city(title)
            if not city:
                logger.warning(f"Could not extract city from: {title}")
                return None
            
            # Strike temperature ve type çıkar
            strike_info = self._extract_strike_info(title)
            
            conditions = event.get('conditions', [])
            condition_id = conditions[0].get('id') if conditions else None
            
            return {
                'event_id': event.get('id'),
                'condition_id': condition_id,
                'title': title,
                'city': city,
                'market_type': strike_info.get('type'),  # "high" veya "low"
                'strike_temp': strike_info.get('temp'),
                'strike_unit': strike_info.get('unit', 'F'),
                'end_date': event.get('end_date'),
                'category': event.get('category'),
                'tags': event.get('tags', []),
                'volume': event.get('volume', 0),
                'liquidity': event.get('liquidity', 0)
            }
        except Exception as e:
            logger.error(f"Parse event error: {e}")
            return None
    
    def _extract_city(self, title: str) -> Optional[str]:
        """Title'dan şehir adı çıkar"""
        title_upper = title.upper()
        
        for city in config.CITIES:
            city_name = city['name'].upper()
            if city_name in title_upper:
                return city['name']
        
        # Alternatif: parantez içindeki şehri bul
        import re
        match = re.search(r'\(([^)]+)\)', title)
        if match:
            potential_city = match.group(1).strip()
            for city in config.CITIES:
                if city['name'].lower() == potential_city.lower():
                    return city['name']
        
        return None
    
    def _extract_strike_info(self, title: str) -> Dict:
        """Title'dan strike temperature ve type çıkar"""
        import re
        
        # Pattern: "High Temperature Above X°F" veya "Low Temperature Below X°F"
        high_match = re.search(r'High.*?(\d+)°?F', title, re.IGNORECASE)
        low_match = re.search(r'Low.*?(\d+)°?F', title, re.IGNORECASE)
        
        if high_match:
            return {
                'type': 'high',
                'temp': int(high_match.group(1)),
                'unit': 'F'
            }
        elif low_match:
            return {
                'type': 'low',
                'temp': int(low_match.group(1)),
                'unit': 'F'
            }
        
        # Alternatif pattern: sadece sayı bul
        temp_match = re.search(r'(\d+)°?F', title)
        if temp_match:
            return {
                'type': 'unknown',
                'temp': int(temp_match.group(1)),
                'unit': 'F'
            }
        
        return {'type': 'unknown', 'temp': 0, 'unit': 'F'}
    
    async def get_result(self, condition_id: str) -> Optional[str]:
        """
        Market sonucunu getir (settled markets için)
        
        Args:
            condition_id: Condition ID
        
        Returns:
            "YES" veya "NO" veya None (henüz çözülmemiş)
        """
        if not self.session:
            await self.start()
        
        url = f"{self.base_url}/conditions/{condition_id}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Settlement status kontrol et
                    if data.get('status') == 'settled':
                        result = data.get('result', '').upper()
                        if result in ['YES', 'NO']:
                            return result
                    
                    # Henüz çözülmemiş
                    return None
                else:
                    logger.error(f"Result fetch error: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Fetch result error: {e}")
            return None
    
    async def scan_markets(self) -> List[Dict]:
        """
        Tüm temperature pazarlarını tara ve analiz için hazırla
        
        Returns:
            List of parsed market data
        """
        events = await self.get_temperature_events()
        
        markets = []
        for event in events:
            parsed = self.parse_event_data(event)
            if parsed:
                # Fiyatları al
                if parsed['condition_id']:
                    prices = await self.get_market_prices(parsed['condition_id'])
                    parsed['yes_price'] = prices['yes']
                    parsed['no_price'] = prices['no']
                    parsed['spread'] = prices['spread']
                
                markets.append(parsed)
        
        logger.info(f"Scanned {len(markets)} markets")
        return markets


# Singleton instance
polymarket_client = PolymarketClient()
