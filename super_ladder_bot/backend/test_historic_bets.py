"""
Test Script - 20 Historic Bets Simulation
Geçmiş tarihlerden 20 farklı bet oluşturur, tarihi ilerletir ve settlement test eder.
"""
import asyncio
import sqlite3
from datetime import datetime, timedelta
import random
from config import config
from database import Database

async def create_test_bets():
    """20 adet test bet oluştur"""
    db = Database(db_path="data/bot.db")
    
    # Test için farklı şehirler ve senaryolar
    test_scenarios = [
        # NYC - High Temperature bets
        {"city": "NYC", "market_type": "high", "strike": 85, "side": "YES", "entry_price": 0.55, "size": 25.0, "days_ago": 5},
        {"city": "NYC", "market_type": "high", "strike": 90, "side": "NO", "entry_price": 0.45, "size": 30.0, "days_ago": 4},
        {"city": "NYC", "market_type": "low", "strike": 70, "side": "YES", "entry_price": 0.60, "size": 20.0, "days_ago": 3},
        
        # Dallas - Hot weather
        {"city": "Dallas", "market_type": "high", "strike": 95, "side": "YES", "entry_price": 0.52, "size": 28.0, "days_ago": 5},
        {"city": "Dallas", "market_type": "high", "strike": 100, "side": "NO", "entry_price": 0.48, "size": 22.0, "days_ago": 4},
        
        # Chicago - Variable weather
        {"city": "Chicago", "market_type": "high", "strike": 80, "side": "YES", "entry_price": 0.58, "size": 25.0, "days_ago": 5},
        {"city": "Chicago", "market_type": "low", "strike": 65, "side": "NO", "entry_price": 0.42, "size": 27.0, "days_ago": 3},
        
        # Los Angeles - Mild weather
        {"city": "Los Angeles", "market_type": "high", "strike": 75, "side": "YES", "entry_price": 0.65, "size": 30.0, "days_ago": 5},
        {"city": "Los Angeles", "market_type": "high", "strike": 80, "side": "NO", "entry_price": 0.35, "size": 20.0, "days_ago": 4},
        
        # Miami - Hot and humid
        {"city": "Miami", "market_type": "high", "strike": 90, "side": "YES", "entry_price": 0.57, "size": 26.0, "days_ago": 5},
        {"city": "Miami", "market_type": "low", "strike": 75, "side": "YES", "entry_price": 0.62, "size": 24.0, "days_ago": 3},
        
        # Seattle - Cool weather
        {"city": "Seattle", "market_type": "high", "strike": 70, "side": "NO", "entry_price": 0.40, "size": 25.0, "days_ago": 5},
        {"city": "Seattle", "market_type": "high", "strike": 65, "side": "YES", "entry_price": 0.55, "size": 23.0, "days_ago": 4},
        
        # London - International
        {"city": "London", "market_type": "high", "strike": 25, "side": "YES", "entry_price": 0.50, "size": 25.0, "days_ago": 5, "is_celsius": True},
        {"city": "London", "market_type": "high", "strike": 30, "side": "NO", "entry_price": 0.45, "size": 22.0, "days_ago": 3, "is_celsius": True},
        
        # Tokyo - International
        {"city": "Tokyo", "market_type": "high", "strike": 30, "side": "YES", "entry_price": 0.58, "size": 27.0, "days_ago": 5, "is_celsius": True},
        {"city": "Tokyo", "market_type": "low", "strike": 25, "side": "YES", "entry_price": 0.53, "size": 24.0, "days_ago": 4, "is_celsius": True},
        
        # Paris - International
        {"city": "Paris", "market_type": "high", "strike": 28, "side": "NO", "entry_price": 0.47, "size": 26.0, "days_ago": 5, "is_celsius": True},
        
        # Boston
        {"city": "Boston", "market_type": "high", "strike": 82, "side": "YES", "entry_price": 0.54, "size": 25.0, "days_ago": 5},
        
        # Denver
        {"city": "Denver", "market_type": "high", "strike": 85, "side": "NO", "entry_price": 0.43, "size": 28.0, "days_ago": 4},
    ]
    
    print(f"🧪 {len(test_scenarios)} adet test bet oluşturuluyor...\n")
    
    total_invested = 0
    with db.get_connection() as conn:
        for i, scenario in enumerate(test_scenarios):
            condition_id = f"test_{scenario['city']}_{scenario['market_type']}_{scenario['strike']}_{scenario['days_ago']}d"
            
            # Bet tarihi (geçmiş)
            bet_date = datetime.now() - timedelta(days=scenario['days_ago'])
            settle_date = bet_date + timedelta(days=1)  # Ertesi gün settlement
            
            # Condition ID formatı
            condition_name = f"{scenario['market_type'].capitalize()} temp in {scenario['city']} on {bet_date.strftime('%Y-%m-%d')}"
            
            # DB'ye insert
            conn.execute("""
                INSERT INTO open_bets (
                    condition_id, event_id, city, region, market_type, strike_temp,
                    side, entry_price, size, model_probability, edge, ev,
                    ladder_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                condition_id,
                f"event_{condition_id}",
                scenario['city'],
                'Test',
                scenario['market_type'],
                scenario['strike'],
                scenario['side'],
                scenario['entry_price'],
                scenario['size'],
                0.55 + random.uniform(-0.1, 0.1),
                random.uniform(0.03, 0.15),
                random.uniform(5, 20),
                'filled',
                bet_date.isoformat(),
                settle_date.isoformat()
            ))
            
            total_invested += scenario['size']
            print(f"  ✅ Bet {i+1}: {scenario['city']} {scenario['market_type']} {scenario['strike']}° "
                  f"{scenario['side']} @ {scenario['entry_price']} (${scenario['size']})")
        
        conn.commit()
    
    print(f"\n💰 Toplam yatırılan: ${total_invested:.2f}")
    
    # Portfolio başlangıç durumunu güncelle
    with db.get_connection() as conn:
        conn.execute("""
            UPDATE portfolio 
            SET current_capital = ?, total_bets = ?
        """, (
            config.STARTING_CAPITAL - total_invested,
            len(test_scenarios)
        ))
        conn.commit()
    
    return test_scenarios

async def simulate_settlement():
    """Tarihi ilerlet ve settlement yap"""
    
    print("\n⏰ Tarih ileri alınıyor ve settlement yapılıyor...\n")
    
    # Tüm open_bets'i al
    db = Database(db_path="data/bot.db")
    
    with db.get_connection() as conn:
        bets = conn.execute("SELECT * FROM open_bets").fetchall()
    
    print(f"📋 {len(bets)} adet açık bet bulundu\n")
    
    total_pnl = 0
    settled_count = 0
    
    for bet in bets:
        condition_id = bet['condition_id']
        city = bet['city']
        side = bet['side']
        entry_price = bet['entry_price']
        size = bet['size']
        market_type = bet['market_type']
        strike = bet['strike_temp']
        
        # Simüle edilmiş sonuç (random ama tutarlı)
        # Gerçekçi olması için city ve strike'a göre deterministic random
        random.seed(condition_id)
        
        if city in ['London', 'Tokyo', 'Paris']:
            # Celsius şehirleri
            actual_temp = random.randint(20, 35)
        else:
            # Fahrenheit şehirleri
            actual_temp = random.randint(65, 105)
        
        # Sonuç belirle
        if market_type == 'high':
            result = "YES" if actual_temp >= strike else "NO"
        else:  # low
            result = "YES" if actual_temp <= strike else "NO"
        
        # Shares hesapla
        shares = size / entry_price
        
        # PnL hesapla
        if side == result:
            # Kazandı
            pnl = shares - size
        else:
            # Kaybetti
            pnl = -size
        
        print(f"  📊 {city} {market_type} {strike}° {side}: "
              f"Actual={actual_temp}°, Result={result}, PnL=${pnl:.2f}")
        
        # Settlement simülasyonu (manuel olarak DB güncelle)
        with db.get_connection() as conn:
            conn.execute("""
                INSERT INTO closed_bets (
                    condition_id, event_id, city, region, market_type, strike_temp,
                    side, entry_price, size, pnl, result, model_probability, edge,
                    created_at, settled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """, (
                condition_id,
                bet['event_id'],
                city,
                bet['region'],
                market_type,
                strike,
                side,
                entry_price,
                size,
                pnl,
                result,
                0.55,  # model_probability
                0.05,  # edge
                bet['created_at']
            ))
            
            # Open bet'i sil
            conn.execute("DELETE FROM open_bets WHERE condition_id = ?", (condition_id,))
            conn.commit()
        
        total_pnl += pnl
        settled_count += 1
    
    # Portfolio güncelle
    current_capital = config.STARTING_CAPITAL + total_pnl
    with db.get_connection() as conn:
        conn.execute("""
            UPDATE portfolio 
            SET current_capital = ?,
                total_pnl = ?,
                daily_pnl = ?,
                winning_bets = (SELECT COUNT(*) FROM closed_bets WHERE pnl > 0),
                losing_bets = (SELECT COUNT(*) FROM closed_bets WHERE pnl <= 0)
        """, (current_capital, total_pnl, total_pnl))
        conn.commit()
    
    print(f"\n✅ {settled_count} adet bet settle edildi")
    print(f"💰 Net PnL: ${total_pnl:.2f}")
    print(f"💵 Yeni Capital: ${current_capital:.2f}")
    
    return total_pnl, current_capital

async def show_results():
    """Sonuçları göster"""
    db = Database(db_path="data/bot.db")
    
    print("\n" + "="*60)
    print("📈 CLOSED BETS RAPORU")
    print("="*60)
    
    with db.get_connection() as conn:
        closed = conn.execute("""
            SELECT city, side, entry_price, size, pnl, result, settled_at
            FROM closed_bets
            ORDER BY settled_at DESC
        """).fetchall()
        
        wins = [b for b in closed if b['pnl'] > 0]
        losses = [b for b in closed if b['pnl'] <= 0]
        
        print(f"\n📊 Toplam: {len(closed)} bet")
        print(f"✅ Kazanan: {len(wins)} ({len(wins)/len(closed)*100:.1f}%)")
        print(f"❌ Kaybeden: {len(losses)} ({len(losses)/len(closed)*100:.1f}%)")
        
        total_won = sum(b['pnl'] for b in wins)
        total_lost = abs(sum(b['pnl'] for b in losses))
        
        print(f"\n💰 Kazanılan: ${total_won:.2f}")
        print(f"💸 Kaybedilen: ${total_lost:.2f}")
        print(f"📈 Net PnL: ${total_won - total_lost:.2f}")
        
        print("\n" + "-"*60)
        print("ŞEHİR PERFORMANSI:")
        print("-"*60)
        
        city_stats = conn.execute("""
            SELECT city, COUNT(*) as count, SUM(pnl) as total_pnl,
                   AVG(pnl) as avg_pnl
            FROM closed_bets
            GROUP BY city
            ORDER BY total_pnl DESC
        """).fetchall()
        
        for stat in city_stats:
            emoji = "🟢" if stat['total_pnl'] > 0 else "🔴"
            print(f"  {emoji} {stat['city']}: {stat['count']} bet, PnL=${stat['total_pnl']:.2f}, Avg=${stat['avg_pnl']:.2f}")
        
        print("\n" + "-"*60)
        print("PORTFOLYO DURUMU:")
        print("-"*60)
        
        portfolio = conn.execute("""
            SELECT current_capital, total_pnl, daily_pnl, 
                   starting_capital, total_bets, winning_bets
            FROM portfolio LIMIT 1
        """).fetchone()
        
        if portfolio:
            print(f"  Başlangıç: ${portfolio['starting_capital']:.2f}")
            print(f"  Şu anki:   ${portfolio['current_capital']:.2f}")
            print(f"  Total PnL: ${portfolio['total_pnl']:.2f} ({portfolio['total_pnl']/portfolio['starting_capital']*100:.2f}%)")
            print(f"  Toplam Bet: {portfolio['total_bets']}")
            if portfolio['total_bets'] > 0:
                print(f"  Win Rate: {portfolio['winning_bets']}/{portfolio['total_bets']} ({portfolio['winning_bets']/portfolio['total_bets']*100:.1f}%)")

async def main():
    print("="*60)
    print("🧪 POLYMARKET SUPER LADDER BOT - TEST SUITE")
    print("="*60)
    print(f"Paper Mode: {config.is_paper_mode}")
    print(f"Starting Capital: ${config.STARTING_CAPITAL}")
    print(f"Max Bet: ${config.max_bet_amount}")
    print(f"Max Exposure: ${config.max_exposure_amount}")
    print(f"Cities: {len(config.CITIES)}")
    print("="*60 + "\n")
    
    # 1. Test betleri oluştur
    scenarios = await create_test_bets()
    
    # 2. Settlement yap
    total_pnl, current_capital = await simulate_settlement()
    
    # 3. Sonuçları göster
    await show_results()
    
    print("\n" + "="*60)
    print("✅ TEST TAMAMLANDI")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
