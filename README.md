# QwenBot - Polymarket Weather Prediction Trading Bot

> Autonomous weather-based prediction market bot for Polymarket.  
> **DRY_RUN mode by default** – real-money trading requires explicit credentials.

---

## Overview

QwenBot scrapes Polymarket weather prediction markets, fetches ensemble weather forecasts, calculates fair probabilities, and places automated bets when positive expected value (EV) is detected. It uses **8-model ensemble forecasting**, **Fractional Kelly sizing**, **ladder order execution**, and a **Self-Improving Algorithm (SIA)** that optimizes model weights over time.

The bot runs as a FastAPI server (port **8091**) with a web dashboard, CLI, and background scheduler.

---

## Architecture

```
QwenBot/
├── main.py                    # FastAPI server + CLI entry point
├── dashboard.html             # Web dashboard (Turkish UI)
├── config/
│   ├── settings.py            # Dataclasses + .env loading
│   └── logging_config.py      # UTF-8 safe logging
├── scrapers/
│   ├── polymarket.py          # Polymarket Gamma API + CLOB scraper
│   ├── meteo.py               # Open-Meteo + WeatherAPI.com fallback
│   └── async_client.py        # Async HTTP client
├── engine/
│   ├── calculator.py          # WeatherEngine: 8-model ensemble consensus
│   ├── strategy.py            # RiskManager, BettingEngine, SIALoop
│   ├── matcher.py             # Weather-market matcher
│   └── market_parser.py       # Market question parser (city, date, type)
├── executor/
│   ├── bet_placer.py          # Bet placement (paper + live, ladder orders)
│   └── settler.py             # Bet settlement + P&L accounting
├── jobs/
│   ├── scheduler.py           # APScheduler background job runner
│   ├── job_fetch_markets.py   # Market fetching
│   ├── job_fetch_weather.py   # Weather data fetching
│   ├── job_analyze.py         # Signal analysis
│   ├── job_place_bets.py      # Bet placement
│   └── job_settle.py          # Settlement
├── database/
│   ├── db.py                  # SQLAlchemy session management
│   └── models.py              # ORM models (Portfolio, Bet, Analysis, etc.)
├── utils/
│   ├── kelly.py               # Kelly criterion bet sizing
│   ├── weights_store.py       # SIA model weight persistence
│   ├── retry.py               # Retry decorator with backoff
│   └── price_sanity.py        # Market price validation
├── data/
│   ├── bot.db                 # SQLite database
│   ├── model_weights.json     # SIA-persisted weights
│   └── strategy_params.json   # SIA-persisted strategy params
└── tests/                     # 20+ pytest test files
```

---

## How It Works

### Pipeline

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  1. FETCH   │────▶│  2. FETCH   │────▶│  3. ANALYZE │────▶│ 4. PLACE    │────▶│  5. SETTLE  │
│  MARKETS    │     │  WEATHER    │     │             │     │  BETS       │     │             │
│ Polymarket  │     │ Open-Meteo  │     │ 8-model     │     │ Kelly /     │     │ Outcome     │
│ Gamma API   │     │ WeatherAPI  │     │ ensemble    │     │ Ladder      │     │ verifi-     │
│             │     │ (fallback)  │     │ Brier score │     │ Risk caps   │     │ cation      │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
```

### Step-by-Step

1. **Fetch Markets** – Scrapes Polymarket weather prediction markets (temperature highs/lows, precipitation, etc.) via Gamma REST API + CLOB.
2. **Fetch Weather** – Queries **Open-Meteo** (primary) and **WeatherAPI.com** (fallback) for 8-model ensemble forecasts grouped by unique city+date (not per-market), deduplicating to avoid rate limits.
3. **Analyze** – WeatherEngine calculates consensus probability (weighted mean), compares against market price. If **edge ≥ min_edge** (default 5%), generates a signal.
4. **Place Bets** – RiskManager enforces caps → Kelly sizes position → ladder levels (if edge > 5%) → BetPlacer executes in paper or live mode.
5. **Settle** – After market resolution, checks actual weather vs market outcome, credits P&L, updates win/loss stats.

---

## Key Features

### 8-Model Ensemble Forecasting
| Model | Source | Weight |
|-------|--------|--------|
| GFS | NOAA | 12.5% |
| ECMWF IFS | ECMWF | 12.5% |
| GEM | Environment Canada | 12.5% |
| ICON | DWD | 12.5% |
| JMA MSM | JMA | 12.5% |
| CMA GRAPES | CMA | 12.5% |
| UKMO | UK Met Office | 12.5% |
| Météo-France | Météo-France | 12.5% |

Weights are dynamically adjusted by **SIA** based on historical Brier scores.

### SIA (Self-Improving Algorithm)
- Runs every **24 hours** (`SIA_INTERVAL=86400`)
- **Model Optimization**: Adjusts model weights using Brier Score on closed bets
- **Financial Feedback**: Tunes `min_edge` and `kelly_fraction` based on win rate and ROI
- Persists weights to `data/model_weights.json` and strategy params to `data/strategy_params.json`

### Ladder Order Execution
When edge ≥ 5%, the bot splits a bet into 3 ladder levels:
| Level | Allocation | Price | Status |
|-------|-----------|-------|--------|
| Level 1 | 50% of stake | Market price | Filled immediately |
| Level 2 | 30% of stake | 2% below market | Pending – fills on dip |
| Level 3 | 20% of stake | 5% below market | Pending – fills on deeper dip |

This averages into positions at better prices during pullbacks.

### Dual Weather API
- **Primary**: Open-Meteo (free, no key required)
- **Fallback**: WeatherAPI.com (requires free API key)
- Rate-limit handling: 30s backoff on 429, deduplicated per city+date

### Risk Management
| Cap | Default | Description |
|-----|---------|-------------|
| Max single bet | 3% of portfolio | `MAX_BET_PCT` |
| Max total exposure | 25% of portfolio | `MAX_EXPOSURE_PCT` |
| Max bets per city | 4 | `CITY_CAP` |
| Daily stop-loss | 5% | `DAILY_LOSS_LIMIT` |
| Kelly fraction | 15% | `KELLY_FRACTION` |
---



## Quick Start

### Prerequisites
- Python 3.12+
- Windows / Linux / macOS

### Installation
```bash
git clone https://github.com/Talcawarrior/QwenBot.git
cd QwenBot
pip install -r requirements.txt
# Edit .env with your settings (copy from existing or create from README table below)
```

### Running
```bash
python main.py run                  # Start server + dashboard
python main.py fetch                # Fetch markets once
python main.py analyze              # Run analysis once
python main.py settle               # Settle resolved bets
python main.py reset                # Reset portfolio
```

Dashboard: **http://127.0.0.1:8092**

---

## Configuration (.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `DRY_RUN` | `true` | Paper mode – no real trades |
| `INITIAL_PORTFOLIO` | `1000.0` | Starting paper balance |
| `SCAN_INTERVAL` | `300` | Market scan frequency (seconds) |
| `SETTLEMENT_INTERVAL` | `120` | Settlement check frequency |
| `SIA_INTERVAL` | `86400` | SIA optimization frequency |
| `MAX_EXPOSURE_PCT` | `0.25` | Max portfolio at risk |
| `MAX_BET_PCT` | `0.03` | Max single bet size |
| `KELLY_FRACTION` | `0.15` | Kelly sizing aggressiveness |
| `CITY_CAP` | `4` | Max concurrent bets per city |

| `POLY_PRIVATE_KEY` | – | Live trading key |
| `POLY_API_KEY` | – | Polymarket API key |
| `WEATHERAPI_KEY` | – | WeatherAPI.com fallback key |
| `HOST` | `127.0.0.1` | Server bind address |
| `PORT` | `8092` | Dashboard port |

---

## Dashboard

The web dashboard at **http://127.0.0.1:8092** features:

**Portfolio Metrics (compact 2×4 grid):**
| Row 1 | Net Sermaye | Açık Bahis | Açık PnL | Kapalı PnL |
| Row 2 | Toplam PnL | Toplam ROI (Kapalı) | Günlük ROI | Açık Bet USD |

**Active Bets Table** – Full P&L tracking per bet with ladder indicators, entry/live edge, price movement.

**Tabs:**
- 🎯 **Aktif Sinyaller** – Active bets with real-time P&L
- 🌍 **Global Market Watch** – All tracked weather markets
- 📊 **Geçmiş Bahisler** – Settlement history
- 📈 **Analytics** – Performance charts (PnL, edge distribution)

**Controls:** Start / Stop / Reset buttons in header (next to status badge)

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard HTML |
| `/api/status` | GET | Bot status + portfolio |
| `/api/start` | POST | Start scan cycle |
| `/api/stop` | POST | Stop scan cycle |
| `/api/reset` | POST | Reset portfolio |
| `/api/signals` | GET | Active signals/bets |
| `/api/history` | GET | Closed bets history |
| `/api/markets` | GET | All tracked markets |
| `/ws` | WebSocket | Real-time updates |

---

## Testing

```bash
# Run all tests
python -m pytest tests/ -v

# Specific test
python -m pytest tests/test_calculator.py -v

# With coverage
python -m pytest tests/ --cov=. --cov-report=html
```

---

## Database (SQLite)

`data/bot.db` contains:

- **Portfolio** – Singleton cash balance tracker
- **WeatherMarket** – Scraped Polymarket markets (city, date, prices)
- **Analysis** – Signal analysis (model probs, edge, EV)
- **Bet** – Placed/settled bets with ladder data, P&L
- **WeatherForecast** – Cached weather predictions per city/date
- **ModelPerformance** – SIA training data (Brier scores)

---

## Known Limitations

- **Paper mode by default** – Live trading requires Polymarket credentials
- **Weather markets only** – Temperature/precipitation prediction markets
- **SQLite** – Single-writer; not suitable for multi-process deployment
- **No hedging** – Simple YES/NO positions only

---

## License

Private repository – All rights reserved.
