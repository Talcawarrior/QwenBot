"""
SQLite Database Setup - WAL Mode ile transaction güvenliği
Paper Trading Edition
"""
import sqlite3
import logging
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class Database:
    """SQLite WAL mode database manager"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_db()
    
    @contextmanager
    def get_connection(self):
        """Thread-safe connection context manager"""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def init_db(self):
        """Database tablolarını oluştur"""
        with self.get_connection() as conn:
            # WAL mode aktif et
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=10000")
            
            # Portfolio tablosu
            conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolio (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    starting_capital REAL NOT NULL,
                    current_capital REAL NOT NULL,
                    total_pnl REAL DEFAULT 0.0,
                    daily_pnl REAL DEFAULT 0.0,
                    total_bets INTEGER DEFAULT 0,
                    winning_bets INTEGER DEFAULT 0,
                    losing_bets INTEGER DEFAULT 0,
                    last_reset_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            
            # Open bets tablosu (aktif bahisler)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS open_bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    condition_id TEXT UNIQUE NOT NULL,
                    event_id TEXT NOT NULL,
                    city TEXT NOT NULL,
                    region TEXT NOT NULL,
                    market_type TEXT NOT NULL,
                    strike_temp REAL NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    size REAL NOT NULL,
                    model_probability REAL NOT NULL,
                    edge REAL NOT NULL,
                    ev REAL NOT NULL,
                    ladder_status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            
            # Closed bets tablosu (tamamlanmış bahisler)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS closed_bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    condition_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    city TEXT NOT NULL,
                    region TEXT NOT NULL,
                    market_type TEXT NOT NULL,
                    strike_temp REAL NOT NULL,
                    side TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    size REAL NOT NULL,
                    pnl REAL NOT NULL,
                    result TEXT NOT NULL,
                    model_probability REAL NOT NULL,
                    edge REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    settled_at TEXT DEFAULT (datetime('now'))
                )
            """)
            
            # Ladder orders tablosu (kademeli emirler)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ladder_orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bet_id INTEGER NOT NULL,
                    condition_id TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    price REAL NOT NULL,
                    size REAL NOT NULL,
                    filled_size REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'pending',
                    order_id TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (bet_id) REFERENCES open_bets(id)
                )
            """)
            
            # Signals log tablosu
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    condition_id TEXT NOT NULL,
                    city TEXT NOT NULL,
                    market_type TEXT NOT NULL,
                    model_probability REAL NOT NULL,
                    market_price REAL NOT NULL,
                    edge REAL NOT NULL,
                    ev REAL NOT NULL,
                    recommended_size REAL NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            
            # Daily stats tablosu
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_stats (
                    date TEXT PRIMARY KEY,
                    starting_capital REAL NOT NULL,
                    ending_capital REAL,
                    daily_pnl REAL DEFAULT 0.0,
                    total_bets INTEGER DEFAULT 0,
                    winning_bets INTEGER DEFAULT 0,
                    losing_bets INTEGER DEFAULT 0,
                    max_drawdown REAL DEFAULT 0.0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            
            # İndeksler
            conn.execute("CREATE INDEX IF NOT EXISTS idx_open_bets_city ON open_bets(city)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_open_bets_condition ON open_bets(condition_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_closed_bets_condition ON closed_bets(condition_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_closed_bets_settled ON closed_bets(settled_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ladder_orders_bet ON ladder_orders(bet_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_log_created ON signals_log(created_at)")
            
            # Portfolio initial row
            conn.execute("""
                INSERT OR IGNORE INTO portfolio (
                    id, starting_capital, current_capital, total_pnl, daily_pnl
                ) VALUES (1, 1000.0, 1000.0, 0.0, 0.0)
            """)
            
            conn.commit()
            logger.info("Database initialized with WAL mode")
    
    def get_portfolio(self) -> dict:
        """Mevcut portfolio durumunu getir"""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM portfolio WHERE id = 1").fetchone()
            if row:
                return dict(row)
            return None
    
    def update_portfolio(self, **kwargs):
        """Portfolio güncelle"""
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [1]
        
        with self.get_connection() as conn:
            conn.execute(f"""
                UPDATE portfolio 
                SET {fields}, updated_at = datetime('now')
                WHERE id = ?
            """, values)
            conn.commit()
    
    def get_open_bets_count(self, city: str = None) -> int:
        """Açık bahis sayısı (şehir bazlı filtreleme)"""
        with self.get_connection() as conn:
            if city:
                row = conn.execute(
                    "SELECT COUNT(*) FROM open_bets WHERE city = ?",
                    (city,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM open_bets").fetchone()
            return row[0] if row else 0
    
    def get_open_exposure(self) -> float:
        """Toplam açık exposure"""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(size), 0) FROM open_bets"
            ).fetchone()
            return row[0] if row else 0.0
    
    def get_region_exposure(self, region: str) -> float:
        """Bölge bazlı exposure"""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(size), 0) FROM open_bets WHERE region = ?",
                (region,)
            ).fetchone()
            return row[0] if row else 0.0
    
    def get_daily_pnl(self) -> float:
        """Günlük PnL"""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT daily_pnl FROM portfolio WHERE id = 1"
            ).fetchone()
            return row[0] if row else 0.0
    
    def reset_daily_pnl(self):
        """Günlük PnL sıfırla"""
        with self.get_connection() as conn:
            conn.execute("""
                UPDATE portfolio 
                SET daily_pnl = 0.0, last_reset_at = datetime('now')
                WHERE id = 1
            """)
            conn.commit()
    
    def add_open_bet(self, bet_data: dict) -> int:
        """Yeni açık bahis ekle"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO open_bets (
                    condition_id, event_id, city, region, market_type,
                    strike_temp, side, entry_price, size,
                    model_probability, edge, ev, ladder_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                bet_data['condition_id'],
                bet_data['event_id'],
                bet_data['city'],
                bet_data['region'],
                bet_data['market_type'],
                bet_data['strike_temp'],
                bet_data['side'],
                bet_data['entry_price'],
                bet_data['size'],
                bet_data['model_probability'],
                bet_data['edge'],
                bet_data['ev'],
                bet_data.get('ladder_status', 'pending')
            ))
            conn.commit()
            return cursor.lastrowid
    
    def add_ladder_order(self, bet_id: int, condition_id: str, level: int, 
                         price: float, size: float) -> int:
        """Ladder emri ekle"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO ladder_orders (
                    bet_id, condition_id, level, price, size, status
                ) VALUES (?, ?, ?, ?, ?, 'pending')
            """, (bet_id, condition_id, level, price, size))
            conn.commit()
            return cursor.lastrowid
    
    def log_signal(self, signal_data: dict):
        """Sinyal logla"""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO signals_log (
                    condition_id, city, market_type, model_probability,
                    market_price, edge, ev, recommended_size, action, reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal_data['condition_id'],
                signal_data['city'],
                signal_data['market_type'],
                signal_data['model_probability'],
                signal_data['market_price'],
                signal_data['edge'],
                signal_data['ev'],
                signal_data['recommended_size'],
                signal_data['action'],
                signal_data.get('reason')
            ))
            conn.commit()
    
    def close_bet(self, condition_id: str, pnl: float, result: str):
        """Bahsi kapat ve closed_bets'e taşı"""
        with self.get_connection() as conn:
            # Open bet bilgilerini al
            bet = conn.execute(
                "SELECT * FROM open_bets WHERE condition_id = ?",
                (condition_id,)
            ).fetchone()
            
            if bet:
                # Closed bets'e ekle
                conn.execute("""
                    INSERT INTO closed_bets (
                        condition_id, event_id, city, region, market_type,
                        strike_temp, side, entry_price, size, pnl, result,
                        model_probability, edge, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    bet['condition_id'], bet['event_id'], bet['city'],
                    bet['region'], bet['market_type'], bet['strike_temp'],
                    bet['side'], bet['entry_price'], bet['size'], pnl, result,
                    bet['model_probability'], bet['edge'], bet['created_at']
                ))
                
                # Ladder orders'ları sil
                conn.execute(
                    "DELETE FROM ladder_orders WHERE condition_id = ?",
                    (condition_id,)
                )
                
                # Open bets'ten sil
                conn.execute(
                    "DELETE FROM open_bets WHERE condition_id = ?",
                    (condition_id,)
                )
                
                # Portfolio güncelle
                portfolio = self.get_portfolio()
                conn.execute("""
                    UPDATE portfolio 
                    SET 
                        current_capital = current_capital + ?,
                        total_pnl = total_pnl + ?,
                        daily_pnl = daily_pnl + ?,
                        total_bets = total_bets + 1,
                        winning_bets = winning_bets + CASE WHEN ? > 0 THEN 1 ELSE 0 END,
                        losing_bets = losing_bets + CASE WHEN ? <= 0 THEN 1 ELSE 0 END,
                        updated_at = datetime('now')
                    WHERE id = 1
                """, (pnl, pnl, pnl, pnl, pnl))
                
                conn.commit()
                logger.info(f"Bet closed: {condition_id}, PnL: {pnl:.2f}")
    
    def get_all_open_bets(self) -> list:
        """Tüm açık bahisleri getir"""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM open_bets ORDER BY created_at DESC").fetchall()
            return [dict(row) for row in rows] if rows else []
    
    def get_ladder_orders(self, condition_id: str) -> list:
        """Bir bahse ait ladder emirlerini getir"""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM ladder_orders WHERE condition_id = ? ORDER BY level",
                (condition_id,)
            ).fetchall()
            return [dict(row) for row in rows] if rows else []
    
    def update_ladder_order(self, order_id: int, **kwargs):
        """Ladder emri güncelle"""
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [order_id]
        
        with self.get_connection() as conn:
            conn.execute(f"""
                UPDATE ladder_orders 
                SET {fields}, updated_at = datetime('now')
                WHERE id = ?
            """, values)
            conn.commit()
    
    def get_recent_signals(self, limit: int = 50) -> list:
        """Son sinyalleri getir"""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM signals_log ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows] if rows else []
    
    def get_closed_bets(self, limit: int = 100) -> list:
        """Tamamlanmış bahisleri getir"""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM closed_bets ORDER BY settled_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows] if rows else []
    
    def get_stats(self) -> dict:
        """Genel istatistikler"""
        with self.get_connection() as conn:
            portfolio = self.get_portfolio()
            open_bets = self.get_open_bets_count()
            closed_count = conn.execute(
                "SELECT COUNT(*) FROM closed_bets"
            ).fetchone()[0]
            
            win_rate = 0.0
            if portfolio['total_bets'] > 0:
                win_rate = portfolio['winning_bets'] / portfolio['total_bets']
            
            return {
                'portfolio': portfolio,
                'open_bets': open_bets,
                'closed_bets': closed_count,
                'win_rate': win_rate,
                'exposure_pct': portfolio['current_capital'] and 
                               (self.get_open_exposure() / portfolio['current_capital']) or 0.0
            }
