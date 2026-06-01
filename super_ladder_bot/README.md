# 🤖 POLYMARKET SUPER LADDER BOT - PAPER TRADING EDITION

## 📋 GENEL BAKIŞ

Polymarket "daily-temperature" pazarlarında otomatik paper trading yapan, kademeli limit emir (ladder) sistemi kullanan bir bot.

**ÖNEMLİ:** Bu bot **PAPER MODE**'da çalışır - gerçek para kullanmaz, sadece simülasyon yapar.

---

## ✨ ÖZELLİKLER

### 🔹 Kademeli Emir Sistemi (Ladder)
- Her bahis 4 kademeli limit emirlere bölünür
- Maker fee = 0 avantajını kullanır
- Fiyat iyileştirme ile daha iyi giriş fiyatı

### 🔹 Çoklu Hava Durumu Modelleri (8+)
- GFS, ECMWF, CMA, JMA, KMA, DWD-ICON, MeteoFrance, UKMO
- Ensemble forecast ile daha güvenilir tahminler
- Model consensus ve confidence skorları

### 🔹 Akıllı Risk Yönetimi
- **Günlük Stop-Loss:** %5 kayıp = bot durur
- **Toplam Exposure:** Max %25 of capital
- **Tek Bet Limiti:** Max %3 of capital
- **Şehir Bazlı Limit:** Max 4 bet per city
- **Bölgesel Korelasyon:** Max %10 per region

### 🔹 Fractional Kelly Criterion
- Otomatik pozisyon boyutlandırma
- Edge ve EV bazlı karar verme
- Minimum $5, maksimum %3 hard limit

### 🔹 Real-time Dashboard
- WebSocket ile anlık güncellemeler
- Portfolio durumu, PnL tracking
- Açık bahisler ve ladder durumları
- Risk alerts ve circuit breaker status

---

## 🚀 HIZLI BAŞLANGIÇ

### Docker ile (Önerilen)

```bash
cd super_ladder_bot
docker-compose up -d
```

Bot `http://localhost:8000` adresinde çalışacaktır.

### Manuel Kurulum

```bash
# Backend dizinine git
cd super_ladder_bot/backend

# Virtual environment oluştur
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Bağımlılıkları yükle
pip install -r requirements.txt

# .env dosyasını düzenle (isteğe bağlı)
cp ../.env.example .env

# Botu başlat
python main.py
```

---

## 📊 API ENDPOINTS

| Endpoint | Method | Açıklama |
|----------|--------|----------|
| `/` | GET | Servis durumu |
| `/api/portfolio` | GET | Portfolio durumu |
| `/api/open-bets` | GET | Açık bahisler + ladder |
| `/api/closed-bets` | GET | Tamamlanmış bahisler |
| `/api/signals` | GET | Son sinyaller |
| `/api/risk-status` | GET | Risk yönetimi durumu |
| `/api/stats` | GET | Komplet istatistikler |
| `/ws` | WebSocket | Real-time updates |

---

## 🔧 KONFİGÜRASYON (.env)

```bash
# PAPER MODE (DAİMA TRUE)
DRY_RUN=true

# CAPITAL
STARTING_CAPITAL=1000.0

# RISK LIMITS
TOTAL_EXPOSURE_PCT=0.25       # Max %25 open bets
MAX_BET_PCT=0.03              # Max %3 per bet
EDGE_THRESHOLD=0.03           # Min %3 edge
KELLY_FRACTION=0.15           # 15% fractional Kelly
DAILY_LOSS_LIMIT=0.05         # %5 daily stop-loss
MAX_BETS_PER_CITY=4           # Max 4 bets per city

# SCANNING
SCAN_INTERVAL=240             # 4 minutes

# DATABASE
DATABASE_PATH=data/bot.db
LOG_PATH=logs/bot.log

# SERVER
API_HOST=0.0.0.0
API_PORT=8000
```

---

## 📁 DOSYA YAPISI

```
super_ladder_bot/
├── backend/
│   ├── config.py              # Konfigürasyon
│   ├── database.py            # SQLite WAL setup
│   ├── weather_engine.py      # 8+ weather models
│   ├── ladder_engine.py       # Order ladder calculator
│   ├── betting_engine.py      # Kelly + Edge + EV
│   ├── polymarket_client.py   # Gamma API client
│   ├── risk_manager.py        # Circuit breakers
│   ├── settlement.py          # Paper settlement
│   ├── main.py                # FastAPI server
│   └── requirements.txt
├── data/                      # SQLite database
├── logs/                      # Log files
├── docker-compose.yml
└── .env
```

---

## 🎮 KULLANIM

### WebSocket Bağlantısı

```javascript
const ws = new WebSocket('ws://localhost:8000/ws');

ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  
  if (message.type === 'portfolio_update') {
    console.log('Portfolio:', message.data);
    // current_capital, total_pnl, daily_pnl, open_bets, etc.
  }
};

// Request open bets
ws.send(JSON.stringify({ type: 'get_open_bets' }));

// Request signals
ws.send(JSON.stringify({ type: 'get_signals' }));

// Reset circuit breaker (if stopped)
ws.send(JSON.stringify({ type: 'reset_circuit_breaker' }));
```

### REST API Örnekleri

```bash
# Portfolio durumu
curl http://localhost:8000/api/portfolio

# Açık bahisler
curl http://localhost:8000/api/open-bets

# Risk durumu
curl http://localhost:8000/api/risk-status

# Komplet stats
curl http://localhost:8000/api/stats
```

---

## ⚠️ RİSK UYARIKLARI

1. **PAPER MODE ONLY:** Bu bot gerçek para kullanmaz. Gerçek trading için önemli modifikasyonlar gerekir.

2. **Circuit Breaker:** Günlük %5 kayıp durumunda bot otomatik durur. Manuel reset gerekir:
   ```bash
   curl -X POST http://localhost:8000/api/reset-circuit-breaker
   ```

3. **Settlement Simülasyonu:** Paper mode'da settlement random olarak simüle edilir. Gerçek bot'ta Polymarket API kullanılmalı.

4. **Weather API Limits:** Open-Meteo ücretsiz tier'de rate limits var. Production için premium plan gerekebilir.

---

## 🧪 TEST KRİTERLERİ

- ✅ `DRY_RUN=true` iken gerçek API çağrısı yok
- ✅ 20+ şehir taranıyor
- ✅ 4 kademeli ladder sistemi çalışıyor
- ✅ Risk limitleri enforced (%25 exposure, %3 max bet, %5 daily stop)
- ✅ Paper mode PnL doğru hesaplanıyor
- ✅ WebSocket real-time updates

---

## 📝 NOTLAR

### Settlement Mantığı
- Paper mode: Model probability'ye weighted random
- Gerçek bot: `polymarket_client.get_result(condition_id)`

### Ladder Stratejisi
- Level 1: %15 @ target - 0.01
- Level 2: %25 @ target - 0.02
- Level 3: %35 @ target - 0.03
- Level 4: %25 @ target - 0.04

### Kelly Formula
```
f* = (bp - q) / b
b = decimal_odds - 1
p = model_probability
q = 1 - p

Fractional Kelly = f* × 0.15
Hard Limit = min(Kelly, capital × 0.03)
```

---

## 🛠️ SORUN GİDERME

### Bot başlamıyor
```bash
# Logları kontrol et
tail -f logs/bot.log

# Database'i sıfırla
rm data/bot.db
python main.py
```

### WebSocket bağlantı kopuyor
- Frontend reconnect logic ekle
- Server loglarını kontrol et

### Hiç sinyal üretmiyor
- Edge threshold'u düşür (0.03 → 0.02)
- Market liquidity kontrol et
- Weather API response'ları incele

---

## 📄 LICENSE

MIT License - Educational purposes only

---

## 🙏 KATKI

Issues ve PR'lar welcome!

---

**⚠️ YASAL UYARI:** Bu yazılım sadece eğitim amaçlıdır. Gerçek para ile trading risklidir. Sorumluluk kabul edilmez.
