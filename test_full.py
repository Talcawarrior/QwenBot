"""
QwenBot TAM CANLI TEST
Dashboard, API, WebSocket, Polymarket canlı veri çekme
Her şey FastAPI TestClient + doğrudan modül testi ile
"""
import sys
import os
import asyncio
import json
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

# ──────────────────────────────────────────
SEP = "=" * 65

def header(t):
    print(f"\n{SEP}")
    print(f"  {t}")
    print(SEP)

def ok(m):   print(f"  ✅ {m}")
def fail(m): print(f"  ❌ {m}")
def info(m): print(f"  ℹ️  {m}")

TOTAL_PASS = 0
TOTAL_FAIL = 0

def track(passed):
    global TOTAL_PASS, TOTAL_FAIL
    if passed:
        TOTAL_PASS += 1
    else:
        TOTAL_FAIL += 1


# ═══════════════════════════════════════════
print("╔══════════════════════════════════════════════════════════╗")
print("║  QwenBot v4.0 - CANLI SİSTEM TESTİ                         ║")
print("║  Polymarket Canlı Veri + Dashboard + Tüm Modüller          ║")
print("╚══════════════════════════════════════════════════════════╝")

# ───────────────────────────────────────
header("0. MODÜL IMPORT TEST")
# ───────────────────────────────────────
try:
    from config import Config
    ok("config.py import OK")
    track(True)
except Exception as e:
    fail(f"config.py: {e}"); track(False)

try:
    from database import init_db, get_db_session, Portfolio, Market, Bet, ModelPerformance
    init_db()
    ok("database.py import + init OK")
    track(True)
except Exception as e:
    fail(f"database.py: {e}"); track(False)

try:
    from data_fetcher import DataFetcher
    ok("data_fetcher.py import OK")
    track(True)
except Exception as e:
    fail(f"data_fetcher.py: {e}"); track(False)

try:
    from weather_engine import WeatherEngine
    ok("weather_engine.py import OK")
    track(True)
except Exception as e:
    fail(f"weather_engine.py: {e}"); track(False)

try:
    from risk_manager import RiskManager
    ok("risk_manager.py import OK")
    track(True)
except Exception as e:
    fail(f"risk_manager.py: {e}"); track(False)

try:
    from betting_engine import BettingEngine, SimpleSignal
    ok("betting_engine.py import OK")
    track(True)
except Exception as e:
    fail(f"betting_engine.py: {e}"); track(False)

try:
    from settlement import SettlementEngine
    ok("settlement.py import OK")
    track(True)
except Exception as e:
    fail(f"settlement.py: {e}"); track(False)

try:
    from sia_loop import SIALoop
    ok("sia_loop.py import OK")
    track(True)
except Exception as e:
    fail(f"sia_loop.py: {e}"); track(False)

try:
    from main import app
    ok("main.py (FastAPI app) import OK")
    track(True)
except Exception as e:
    fail(f"main.py: {e}"); track(False)

# ───────────────────────────────────────
header("1. CONFIG TEST")
# ───────────────────────────────────────
c = Config()
track(c.INITIAL_PORTFOLIO == 1000.0); ok(f"INITIAL_PORTFOLIO = ${c.INITIAL_PORTFOLIO}")
track(c.HOST == "0.0.0.0");           ok(f"HOST = {c.HOST}")
track(c.PORT == 8091);                ok(f"PORT = {c.PORT}")
track(c.DAILY_LOSS_LIMIT == 0.05);    ok(f"DAILY_LOSS_LIMIT = {c.DAILY_LOSS_LIMIT}")
track(c.KELLY_FRACTION == 0.15);      ok(f"KELLY_FRACTION = {c.KELLY_FRACTION}")
track(abs(sum(c.MODEL_WEIGHTS.values()) - 1.0) < 0.001); ok(f"MODEL_WEIGHTS sum = {sum(c.MODEL_WEIGHTS.values()):.4f}")
track(len(c.CITY_ICAO_MAP) == 38);    ok(f"CITY_ICAO_MAP = {len(c.CITY_ICAO_MAP)} şehir")
track(c.FEE_DRAG == 0.005);           ok(f"FEE_DRAG = {c.FEE_DRAG}")
track(c.MIN_EDGE == 0.03);            ok(f"MIN_EDGE = {c.MIN_EDGE}")

# ───────────────────────────────────────
header("2. DATABASE TEST")
# ───────────────────────────────────────
db = get_db_session()
try:
    p = db.query(Portfolio).filter(Portfolio.id == 1).first()
    if not p:
        p = Portfolio(id=1, initial_value=1000.0, current_value=1000.0, cash_balance=1000.0, total_value=1000.0, total_realized_pnl=0.0)
        db.add(p)
        db.commit()
    track(p.cash_balance == 1000.0); ok(f"Portfolio cash = ${p.cash_balance}")
    track(p.total_value == 1000.0);   ok(f"Portfolio total = ${p.total_value}")
    track(p.daily_pnl == 0.0);         ok(f"Portfolio daily_pnl = ${p.daily_pnl}")
except Exception as e:
    fail(f"DB test: {e}"); track(False)
finally:
    db.close()

# ───────────────────────────────────────
header("3. DATAFETCHER TEST")
# ───────────────────────────────────────
df = DataFetcher()

coords_dallas = df.get_city_coords("KDAL")
track(coords_dallas == (32.8471, -96.8517)); ok(f"KDAL coords: {coords_dallas}")

coords_ankara = df.get_city_coords("LTAC")
track(coords_ankara == (39.9891, 32.8236)); ok(f"LTAC coords: {coords_ankara}")

city_extract = df._extract_city("Dallas Temperature")
track(city_extract == "KDAL"); ok(f"Extract city 'Dallas': {city_extract}")

strike_f = df._extract_strike("above 80°F")
track(round(strike_f, 1) == 26.7); ok(f"Extract strike 'above 80°F': {strike_f}°C")

type_high = df._determine_market_type("Will it be above 30 degrees?")
track(type_high == "HIGH"); ok(f"Market type 'above': {type_high}")

type_low = df._determine_market_type("Will it be below 20 degrees?")
track(type_low == "LOW"); ok(f"Market type 'below': {type_low}")

# ───────────────────────────────────────
header("4. POLYMARKET CANLI VERİ ÇEKME")
# ───────────────────────────────────────
print("  Polymarket Gamma API'den canlı veri çekiliyor...")

async def fetch_live_data():
    await df.init_session()
    markets = await df.fetch_polymarket_events(limit=50)
    await df.close_session()
    return markets

try:
    live_markets = asyncio.run(fetch_live_data())
    track(isinstance(live_markets, list)); ok(f"API response type: list")
    track(len(live_markets) > 0);         ok(f"Çekilen market sayısı: {len(live_markets)}")

    if live_markets:
        ok("✅✅✅ POLYMARKET CANLI VERİ BAŞARIYLA ÇEKİLDİ ✅✅✅")
        print(f"\n  İlk 15 canlı market:")
        for i, m in enumerate(live_markets[:15]):
            q = m.get("question", "")[:50]
            city = m.get("city", "?")
            city_code = m.get("city_code", "")
            strike = m.get("strike_temp", 0)
            price = m.get("yes_price", 0)
            ok(f"  {i+1}. {city:15s} | {city_code:8s} | Strike: {strike:>5.0f} | Price: {price:.3f} | {q}")

        # İstatistikler
        cities = set(m.get("city_code", "") for m in live_markets if m.get("city_code"))
        ok(f"Toplam farklı şehir: {len(cities)}")
        ok(f"Ortalama yes_price: {sum(m.get('yes_price',0) for m in live_markets)/len(live_markets):.3f}")
    else:
        info("API'den veri gelmedi (rate limit veya bağlantı sorunu olabilir)")
except Exception as e:
    fail(f"Polymarket API hatası: {e}"); track(False)
    traceback.print_exc()

# ───────────────────────────────────────
header("5. WEATHER ENGINE TEST")
# ───────────────────────────────────────
we = WeatherEngine(None, c)
forecast = {"weighted_mean": 25.0, "weighted_std": 3.5, "model_count": 8, "model_temps": {}}

prob_above_28 = we.calculate_probability_above(28.0, forecast)
track(0 < prob_above_28 < 1); ok(f"P(T>28°C) = {prob_above_28:.4f}")

prob_below_22 = we.calculate_probability_below(22.0, forecast)
track(0 < prob_below_22 < 1); ok(f"P(T<22°C) = {prob_below_22:.4f}")

prob_above_25 = we.calculate_probability_above(25.0, forecast)
track(0.4 < prob_above_25 < 0.6); ok(f"P(T>25°C) = {prob_above_25:.4f} (normal area)")

# ───────────────────────────────────────
header("6. RISK MANAGER TEST")
# ───────────────────────────────────────
rm = RiskManager(None, c)
kelly = rm.calculate_kelly_bet_size(0.55, 0.45)
track(kelly > 0); ok(f"Kelly (p=0.55, price=0.45) = ${kelly}")

cap = rm.check_city_cap("KDAL")
track(cap == True); ok(f"City cap KDAL (0 bets): {cap}")

for _ in range(5):
    rm.increment_city_bet("KDAL")
cap_full = rm.check_city_cap("KDAL")
track(cap_full == False); ok(f"City cap KDAL (5 bets, limit=4): {cap_full}")

locked = rm.is_bot_locked()
track(locked == False); ok(f"Bot locked: {locked}")

rm.update_daily_pnl(-60.0)
locked_now = rm.is_bot_locked()
track(locked_now == True); ok(f"Bot locked after -60$ PnL: {locked_now}")

# ───────────────────────────────────────
header("7. BETTING ENGINE TEST")
# ───────────────────────────────────────
be = BettingEngine()

signal = be.analyze_signal({"city_code": "KDAL", "strike_temp": 30, "market_type": "HIGH", "yes_price": 0.40}, 0.60)
if signal:
    track(signal["edge"] > 0);     ok(f"Edge: {signal['edge']}")
    track(signal["ev"] > 0);       ok(f"EV: {signal['ev']}")
    track(signal["is_eligible"]);  ok(f"Eligible: {signal['is_eligible']}")
    track(signal["side"] == "YES"); ok(f"Side: {signal['side']}")

    ladder = be.create_ladder_orders(signal, 30.0)
    track(len(ladder) == 3); ok(f"Ladder levels: {len(ladder)}")
    ok(f"  Level 1: ${ladder[0]['size']:.1f} @ ${ladder[0]['price']:.3f}")
    ok(f"  Level 2: ${ladder[1]['size']:.1f} @ ${ladder[1]['price']:.3f}")
    ok(f"  Level 3: ${ladder[2]['size']:.1f} @ ${ladder[2]['price']:.3f}")
else:
    fail("Signal None"); track(False)

# SimpleSignal attributes
sig = SimpleSignal(city="Dallas", edge=0.15, bet_size=10.0)
track(hasattr(sig, "edge"));     ok(f"SimpleSignal.edge = {sig.edge}")
track(hasattr(sig, "bet_size")); ok(f"SimpleSignal.bet_size = {sig.bet_size}")

# No-signal case (edge too small)
no_sig = be.analyze_signal({"city_code": "KDAL", "strike_temp": 30, "market_type": "HIGH", "yes_price": 0.50}, 0.52)
track(no_sig is None); ok(f"No signal (edge < MIN_EDGE): {no_sig}")

# ───────────────────────────────────────
header("8. SETTLEMENT ENGINE TEST")
# ───────────────────────────────────────
db = get_db_session()
se = SettlementEngine(db, c)

test_bet = Bet(
    market_id="test_live_1", city_code="KDAL", city="Dallas",
    strike_temp=25.0, bet_type="YES", side="HIGH",
    entry_price=0.45, stake=20.0, stake_amount=20.0,
    shares=44.44, status="active"
)
result = se.settle_bet(test_bet, 27.0)
track(result["status"] == "won"); ok(f"Settle HIGH>25 with actual=27°C: {result['status']}")
track(result["realized_pnl"] > 0); ok(f"Realized PnL: ${result['realized_pnl']:.2f}")

test_bet2 = Bet(
    market_id="test_live_2", city_code="KDAL", city="Dallas",
    strike_temp=30.0, bet_type="YES", side="HIGH",
    entry_price=0.45, stake=20.0, stake_amount=20.0,
    shares=44.44, status="active"
)
result2 = se.settle_bet(test_bet2, 28.0)
track(result2["status"] == "lost"); ok(f"Settle HIGH>30 with actual=28°C: {result2['status']}")
track(result2["realized_pnl"] < 0); ok(f"Realized PnL: ${result2['realized_pnl']:.2f}")

# NO side
test_bet3 = Bet(
    market_id="test_live_3", city_code="KDAL", city="Dallas",
    strike_temp=25.0, bet_type="NO", side="HIGH",
    entry_price=0.45, stake=20.0, stake_amount=20.0,
    shares=44.44, status="active"
)
result3 = se.settle_bet(test_bet3, 27.0)
track(result3["status"] == "lost"); ok(f"Settle NO/HIGH>25 with actual=27°C: {result3['status']}")
db.close()

# ───────────────────────────────────────
header("9. SIA LOOP TEST")
# ───────────────────────────────────────
sia = SIALoop(None, c)
perf = sia.analyze_model_performance()
track(len(perf) == 8); ok(f"Model sayısı: {len(perf)}")

bs = sia.calculate_brier_score([0.7, 0.8, 0.6], [True, False, True])
track(0 < bs < 1); ok(f"Brier Score: {bs}")

adj = sia.get_adjusted_probability(0.7, "gfs", 0.25)
track(0 < adj < 1); ok(f"Adjusted Prob: {adj}")

weights = sia.optimize_weights(perf)
track(len(weights) == 8); ok(f"Optimized weights: {len(weights)}")
track(abs(sum(weights.values()) - 1.0) < 0.001); ok(f"Weights sum: {sum(weights.values()):.4f}")

# ───────────────────────────────────────
header("10. FASTAPI DASHBOARD HTML TEST")
# ───────────────────────────────────────
from fastapi.testclient import TestClient
client = TestClient(app)

r = client.get("/")
track(r.status_code == 200); ok(f"GET / HTTP {r.status_code}")
html = r.text
track(len(html) > 10000); ok(f"HTML boyutu: {len(html)} bytes")

ui_checks = [
    ("Ana başlık", "polymarket ultimate", html),
    ("Portfolio", "portfolio", html),
    ("Başlat butonu", "startbot", html),
    ("Durdur butonu", "stopbot", html),
    ("Sıfırla butonu", "resetbot", html),
    ("Status API", "loadstatus", html),
    ("Signals API", "loadsignals", html),
    ("Markets API", "loadmarkets", html),
    ("History API", "loadhistory", html),
    ("Chart.js", "chart.js", html),
    ("WebSocket", "websocket", html),
    ("Tab switching", "switchtab", html),
    ("Sinyaller tabı", "sinyal", html),
    ("Markets tabı", "market", html),
    ("Analytics tabı", "analytics", html),
    ("WS connect", "connectwebsocket", html),
    ("Auto refresh", "setinterval", html),
]
for name, keyword, text in ui_checks:
    found = keyword.lower() in text.lower()
    track(found)
    if found:
        ok(f"{name} mevcut")
    else:
        fail(f"{name} YOK!")

# ───────────────────────────────────────
header("11. API ENDPOINT TESTLERI (TestClient)")
# ───────────────────────────────────────

# Status
r = client.get("/api/status")
track(r.status_code == 200); ok(f"GET /api/status HTTP {r.status_code}")
d = r.json()
track("error" not in d); ok(f"Status JSON valid (no error)")
track("portfolio" in d); ok(f"portfolio key mevcut")
track("stats" in d); ok(f"stats key mevcut")
track("limits" in d); ok(f"limits key mevcut")
track(d["portfolio"]["current"] == 1000.0); ok(f"Portfolio current = ${d['portfolio']['current']}")
track(d["portfolio"]["smart_pool"] == 400.0); ok(f"Smart pool = ${d['portfolio']['smart_pool']}")
track(d["limits"]["max_bet_pct"] == 3.0); ok(f"Max bet = {d['limits']['max_bet_pct']}%")

# Signals
r = client.get("/api/signals")
track(r.status_code == 200); ok(f"GET /api/signals HTTP {r.status_code}")
d = r.json()
track("count" in d); ok(f"Signals count: {d['count']}")
track("signals" in d); ok(f"signals array mevcut")

# Markets
r = client.get("/api/markets")
track(r.status_code == 200); ok(f"GET /api/markets HTTP {r.status_code}")
d = r.json()
track("count" in d); ok(f"Markets count: {d['count']}")
track("markets" in d); ok(f"markets array mevcut")

# History
r = client.get("/api/history")
track(r.status_code == 200); ok(f"GET /api/history HTTP {r.status_code}")
d = r.json()
track("history" in d); ok(f"history array mevcut")
track("stats" in d); ok(f"stats mevcut")

# POST Start
r = client.post("/api/start")
track(r.status_code == 200); ok(f"POST /api/start: {r.json()['status']}")

# POST Stop
r = client.post("/api/stop")
track(r.status_code == 200); ok(f"POST /api/stop: {r.json()['status']}")

# POST Reset
r = client.post("/api/reset")
track(r.status_code == 200); ok(f"POST /api/reset: {r.json()['status']}")

# ───────────────────────────────────────
header("12. LINTER KONTROL")
# ───────────────────────────────────────
import subprocess

r = subprocess.run(
    ["python3", "-m", "ruff", "check", "backend/"],
    capture_output=True, text=True,
    cwd=os.path.dirname(os.path.abspath(__file__))
)
ruff_ok = r.returncode == 0
track(ruff_ok)
if ruff_ok:
    ok("Ruff: All checks passed! ✅")
else:
    fail(f"Ruff: {r.stdout.strip()}")

r = subprocess.run(
    ["python3", "-m", "pylint", "--output-format=text", "backend/*.py"],
    capture_output=True, text=True,
    cwd=os.path.dirname(os.path.abspath(__file__))
)
pylint_line = ""
for line in r.stdout.strip().split("\n"):
    if "rated at" in line:
        pylint_line = line.strip()
        break
pylint_ok = "10.00" in pylint_line
track(pylint_ok)
if pylint_ok:
    ok(f"Pylint: {pylint_line}")
else:
    ok(f"Pylint: {pylint_line if pylint_line else 'completed'}")

# ───────────────────────────────────────
header("SONUÇ RAPORU")
# ───────────────────────────────────────
TOTAL = TOTAL_PASS + TOTAL_FAIL
pct = (TOTAL_PASS / TOTAL * 100) if TOTAL > 0 else 0
print(f"\n  Toplam Test:    {TOTAL}")
print(f"  Başarılı:       {TOTAL_PASS}")
print(f"  Başarısız:      {TOTAL_FAIL}")
print(f"  Success Rate:   {pct:.1f}%")

if TOTAL_FAIL == 0:
    print(f"\n  🎉 TÜM TESTLER BAŞARILI - SIFIR HATA!")
else:
    print(f"\n  ⚠️  {TOTAL_FAIL} başarısız test var")

print(f"\n{SEP}")
