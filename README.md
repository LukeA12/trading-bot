# Prediction Market Trading Bot — Complete Technical Reference

This document is a complete specification of the codebase: architecture, data models, algorithms, API contracts, configuration, and operational flows. It is written to be self-contained enough that a developer (or another AI) could rebuild the system from scratch.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Repository Layout](#2-repository-layout)
3. [Tech Stack](#3-tech-stack)
4. [Configuration & Environment](#4-configuration--environment)
5. [Database Layer](#5-database-layer)
6. [Backend: FastAPI Application](#6-backend-fastapi-application)
7. [REST API Reference](#7-rest-api-reference)
8. [WebSocket API](#8-websocket-api)
9. [Background Scheduler (Orchestrator)](#9-background-scheduler-orchestrator)
10. [BTC Analysis Engine](#10-btc-analysis-engine)
11. [Weather Analysis Engine](#11-weather-analysis-engine)
12. [Weather Trading Strategies](#12-weather-trading-strategies)
13. [Settlement & Resolution Engine](#13-settlement--resolution-engine)
14. [External Data Sources](#14-external-data-sources)
15. [LLM Integration](#15-llm-integration)
16. [Frontend Architecture](#16-frontend-architecture)
17. [Frontend Components](#17-frontend-components)
18. [End-to-End Data Flows](#18-end-to-end-data-flows)
19. [Risk Controls](#19-risk-controls)
20. [Deployment](#20-deployment)

---

## 1. System Overview

This is a fully automated prediction-market trading bot that operates on two market categories:

- **BTC 5-minute markets** (Polymarket): Binary contracts that pay $1 if BTC moves up or down within a 5-minute window. The bot derives a model probability from real-time technical analysis of BTC price candles and compares it to the market's implied probability to find mispricings.
- **Weather temperature markets** (Polymarket + Kalshi): Binary/range contracts on daily high/low temperatures in US cities. The bot uses ensemble weather forecasts (20+ NWP models) to compute the true probability of a threshold being crossed and compares it to market prices.

The bot runs a FastAPI backend that manages a background scheduler, stores everything in SQLite (or PostgreSQL), and serves a React dashboard. The dashboard displays portfolio metrics, equity curves split by strategy and platform, a calibration tracker, a live activity terminal, and weather forecasts.

**Core loop:**
1. Fetch active contracts from prediction market APIs
2. Compute model probability (technical analysis for BTC, ensemble weather for temperature)
3. Calculate edge = model probability − market price
4. Size positions with fractional Kelly criterion
5. Execute trades (or simulate them) and persist positions
6. Periodically poll market APIs to settle resolved positions and update P&L
7. Stream all activity to the frontend via WebSocket and REST

---

## 2. Repository Layout

```
trading-bot/
├── run.py                          # Entry point — launches uvicorn on port 8000
├── main.py                         # (empty placeholder)
├── requirements.txt                # Python dependencies
├── Procfile                        # Railway/Heroku deployment: `python run.py`
├── .env.example                    # Template for all environment variables
├── export_trades.py                # CLI utility to export trade history to CSV
├── test_connectivity.py            # Checks API reachability for all data sources
│
├── backend/
│   ├── env.py                      # AppConfig (pydantic-settings + AWS Secrets Manager)
│   │
│   ├── server/
│   │   └── app.py                  # FastAPI app: all routes, DTOs, WebSocket hub
│   │
│   ├── storage/
│   │   └── models.py               # SQLAlchemy ORM: all table definitions + migrations
│   │
│   ├── engine/
│   │   ├── orchestrator.py         # APScheduler cycles, activity log, trade execution logic
│   │   ├── analysis.py             # BTC signal evaluation: technicals → edge → Kelly sizing
│   │   ├── resolution.py           # Settlement engine: polls Polymarket/Kalshi for outcomes
│   │   ├── wx_analysis.py          # Weather signal evaluation: ensemble → edge → sizing
│   │   └── wx_strategies.py        # Strategy 1/2/3 constants and sizing functions
│   │
│   ├── sources/
│   │   ├── polymarket_btc.py       # Fetches active BTC 5-min windows from Polymarket Gamma API
│   │   ├── polymarket_weather.py   # Fetches weather temperature contracts from Polymarket
│   │   ├── kalshi_api.py           # Kalshi REST connector with RSA-PSS authentication
│   │   ├── kalshi_weather.py       # Fetches weather temperature contracts from Kalshi
│   │   ├── price_feed.py           # BTC candle fetcher (4-exchange cascade) + technical indicators
│   │   ├── ensemble_forecast.py    # Weather ensemble loader (Open-Meteo + NWS)
│   │   └── market_adapter.py       # Normalizes market data to a unified format
│   │
│   └── llm/
│       ├── anthropic_client.py     # Claude API client for deep analysis
│       ├── groq_client.py          # Groq/Llama client for fast classification
│       ├── types.py                # LLM type definitions and prompt builders
│       └── tracking.py             # LLM call logging and cost tracking
│
└── frontend/
    ├── package.json                # npm dependencies
    ├── vite.config.ts              # Vite build config
    ├── tailwind.config.js          # Tailwind CSS config
    ├── tsconfig.json               # TypeScript config
    ├── vercel.json                 # Vercel deployment config
    ├── railway.json                # Railway deployment config
    └── src/
        ├── main.tsx                # React entry point, React Query provider
        ├── App.tsx                 # Root component, layout, polling, bot controls
        ├── api.ts                  # Axios API client — all backend calls
        ├── types.ts                # TypeScript type definitions matching backend DTOs
        └── components/
            ├── StatsCards.tsx      # Portfolio summary chips (bankroll, P&L, win rate)
            ├── EquityChart.tsx     # Recharts equity curve, strategy/platform toggle
            ├── TradesTable.tsx     # Scrollable trade history with P&L coloring
            ├── Terminal.tsx        # Real-time activity log, bot start/stop controls
            ├── CalibrationPanel.tsx# Brier score and prediction accuracy display
            ├── WeatherPanel.tsx    # Weather forecast cards + signal list
            ├── FilterBar.tsx       # UI filter controls
            ├── GlobeView.tsx       # Geographic weather visualization
            ├── EdgeDistribution.tsx# Edge statistics histogram
            ├── MicrostructurePanel.tsx # Real-time BTC technical indicator display
            └── SignalsTable.tsx    # Active trading signals table
```

---

## 3. Tech Stack

### Backend
| Layer | Technology |
|---|---|
| Web framework | FastAPI 0.100+ with Uvicorn ASGI server |
| ORM | SQLAlchemy 2.0 (declarative base) |
| Database | SQLite (default) or PostgreSQL (via `DATABASE_URL`) |
| Scheduler | APScheduler 3.x with `AsyncIOScheduler` |
| HTTP client | httpx (async) |
| Config | pydantic-settings (reads `.env` + AWS Secrets Manager) |
| Auth (Kalshi) | RSA-PSS digital signatures (cryptography library) |

### Frontend
| Layer | Technology |
|---|---|
| Framework | React 18 + TypeScript |
| Build tool | Vite |
| Server state | TanStack React Query v5 |
| HTTP | Axios |
| Charts | Recharts |
| Animations | Framer Motion |
| Styling | Tailwind CSS |

### External Services
| Service | Purpose |
|---|---|
| Polymarket Gamma API | BTC windows + weather contracts + settlement data |
| Kalshi REST API | Weather temperature contracts + settlement data |
| Coinbase Exchange API | Primary BTC 1-minute candles |
| Kraken API | Fallback BTC candles |
| Binance API | Fallback BTC candles |
| Bybit API | Fallback BTC candles |
| CoinGecko API | BTC spot price + 24h/7d change |
| Open-Meteo API | Ensemble weather forecast (no auth) |
| NWS (weather.gov) | Historical temperature observations |
| AWS Secrets Manager | Production API key storage (optional) |
| Anthropic Claude API | Deep market analysis (optional) |
| Groq API (Llama) | Fast text classification (optional) |

---

## 4. Configuration & Environment

### How Configuration Loads

`backend/env.py` uses **pydantic-settings** (`AppConfig(BaseSettings)`). At module load time, the code:
1. Calls `_load_aws_secrets()` which attempts to fetch a JSON bundle from AWS Secrets Manager (secret name from `AWS_SECRET_NAME` env var, defaults to `trading-bot/api-keys`).
2. Injects any fetched secrets into `os.environ` *only if those keys aren't already set*, so local `.env` values always take precedence.
3. Instantiates `AppConfig()` which reads from `.env` file and the process environment.

This means locally you use a `.env` file; in production you populate AWS Secrets Manager.

### All Configuration Variables

```ini
# --- Persistence ---
DATABASE_URL=sqlite:///./tradingbot.db          # or postgresql://user:pass@host/db

# --- External API credentials ---
POLYMARKET_API_KEY=                             # Optional (public endpoints don't need it)
KALSHI_API_KEY_ID=                              # Kalshi key ID for RSA auth
KALSHI_PRIVATE_KEY_PATH=/path/to/kalshi.pem    # Path to RSA private key PEM file
GROQ_API_KEY=                                   # Groq API key for Llama models
ANTHROPIC_API_KEY=                              # Anthropic API key for Claude

# --- LLM settings ---
GROQ_MODEL=llama-3.1-8b-instant                # Which Groq model to use
AI_LOG_ALL_CALLS=true                           # Persist all LLM calls to ai_logs table
AI_DAILY_BUDGET_USD=1.0                         # Max USD spend per day on LLMs

# --- Platform toggles ---
POLYMARKET_ENABLED=true
KALSHI_ENABLED=true
BTC_ENABLED=true

# --- Execution ---
SIMULATION_MODE=true                            # If true, no real money moves
INITIAL_BANKROLL=10000.0                        # Starting capital in USD
KELLY_FRACTION=0.15                             # Fraction of full Kelly to use (15%)

# --- BTC scan settings ---
SCAN_INTERVAL_SECONDS=60                        # How often to run BTC scan cycle
SETTLEMENT_INTERVAL_SECONDS=120                 # How often to check settlements
MIN_EDGE_THRESHOLD=0.02                         # Minimum edge to act on (2%)
MAX_ENTRY_PRICE=0.55                            # Don't enter if market price > 55¢
MAX_TRADES_PER_WINDOW=1                         # Max trades per market window
MAX_TOTAL_PENDING_TRADES=20                     # Global cap on open positions
BTC_PRICE_SOURCE=coinbase                       # Default price source hint

# --- BTC time filters ---
MIN_TIME_REMAINING=60                           # Don't enter with < 60 sec left
MAX_TIME_REMAINING=1800                         # Don't enter with > 30 min left

# --- BTC position sizing ---
MAX_TRADE_SIZE=75.0                             # Hard cap per BTC trade in USD

# --- Risk controls ---
DAILY_LOSS_LIMIT=300.0                          # Stop trading if daily loss hits this
MIN_MARKET_VOLUME=100.0                         # Minimum market volume to consider

# --- BTC composite signal weights (must sum conceptually) ---
WEIGHT_RSI=0.20
WEIGHT_MOMENTUM=0.35
WEIGHT_VWAP=0.20
WEIGHT_SMA=0.15
WEIGHT_MARKET_SKEW=0.10

# --- Weather settings ---
WEATHER_ENABLED=true
WEATHER_SCAN_INTERVAL_SECONDS=300              # How often to scan weather markets
WEATHER_SETTLEMENT_INTERVAL_SECONDS=1800       # How often to check weather settlements
WEATHER_MIN_EDGE_THRESHOLD=0.08                # Minimum edge for weather (8%)
WEATHER_MAX_ENTRY_PRICE=0.70                   # Max entry price for weather (70¢)
WEATHER_MAX_TRADE_SIZE=100.0                   # Max trade size for weather
WEATHER_CITIES=nyc,chicago,miami,los_angeles,denver  # Cities to scan

# --- AWS (for production secret loading) ---
AWS_SECRET_NAME=trading-bot/api-keys
AWS_REGION=us-east-1
```

---

## 5. Database Layer

### Schema Overview (`backend/storage/models.py`)

All tables are created via SQLAlchemy's `Base.metadata.create_all()` at startup. Incremental column additions (for forward compatibility) are handled by `migrate_schema()`, which uses raw `ALTER TABLE` statements.

### Table: `trades` (model: `Position`)

The primary ledger of all positions opened by the bot.

| Column | Type | Description |
|---|---|---|
| `id` | Integer PK | Auto-increment |
| `signal_id` | Integer (FK ref) | Links to `signals.id` (the opportunity that triggered this trade) |
| `market_ticker` | String | The prediction market's unique ID |
| `platform` | String | `"polymarket"` or `"kalshi"` |
| `event_slug` | String (nullable) | Polymarket event slug for resolution lookup |
| `market_type` | String | `"btc"` or `"weather"` |
| `direction` | String | `"up"/"down"` (BTC) or `"yes"/"no"` (weather) |
| `entry_price` | Float | Price paid (e.g. `0.43` = 43¢ per $1 contract) |
| `size` | Float | Dollar amount wagered |
| `timestamp` | DateTime | When position was opened |
| `settled` | Boolean | False until market resolves |
| `settlement_time` | DateTime (nullable) | When market resolved |
| `settlement_value` | Float (nullable) | `1.0` if our direction won, `0.0` if lost |
| `result` | String | `"pending"`, `"win"`, `"loss"`, `"push"` |
| `pnl` | Float (nullable) | Net profit/loss in USD |
| `model_probability` | Float | Our model's P(up/yes) at entry time |
| `market_price_at_entry` | Float | Market's implied probability at entry |
| `edge_at_entry` | Float | Edge at time of entry (model − market) |
| `strategy` | Integer | Strategy ID: 1, 2, or 3 |

### Table: `bot_state` (model: `PortfolioState`)

A single row tracking the bot's aggregate state.

| Column | Type | Description |
|---|---|---|
| `id` | Integer PK | Always 1 (singleton row) |
| `bankroll` | Float | Current capital (starts at `INITIAL_BANKROLL`, moves with P&L) |
| `total_trades` | Integer | Cumulative trade count |
| `winning_trades` | Integer | Count of trades where `result = "win"` |
| `total_pnl` | Float | Cumulative P&L in USD |
| `last_run` | DateTime | Timestamp of last scan cycle |
| `is_running` | Boolean | Whether automated trading is enabled |

### Table: `signals` (model: `Opportunity`)

Every signal generated by the analysis engine, regardless of whether executed. Used for calibration.

| Column | Type | Description |
|---|---|---|
| `id` | Integer PK | Auto-increment |
| `market_ticker` | String | Market ID |
| `platform` | String | `"polymarket"` or `"kalshi"` |
| `market_type` | String | `"btc"` or `"weather"` |
| `timestamp` | DateTime | When signal was generated |
| `direction` | String | Predicted direction |
| `model_probability` | Float | Model's P(up/yes) |
| `market_price` | Float | Market's implied probability at signal time |
| `edge` | Float | model_probability − market_price |
| `confidence` | Float | Model confidence [0, 1] |
| `kelly_fraction` | Float | Raw Kelly fraction (before capping) |
| `suggested_size` | Float | Kelly-sized stake in USD |
| `sources` | JSON | List of data sources used |
| `reasoning` | String | Human-readable explanation of the signal |
| `executed` | Boolean | Whether a Position was opened from this signal |
| `actual_outcome` | String (nullable) | `"up"` or `"down"` after settlement |
| `outcome_correct` | Boolean (nullable) | Whether our direction prediction was correct |
| `settlement_value` | Float (nullable) | The final market settlement value |
| `settled_at` | DateTime (nullable) | When the linked trade settled |

### Table: `ai_logs` (model: `LLMLog`)

Full audit trail of every LLM API call made.

| Column | Type | Description |
|---|---|---|
| `id` | Integer PK | Auto-increment |
| `timestamp` | DateTime | When call was made |
| `provider` | String | `"anthropic"` or `"groq"` |
| `model` | String | Model name used |
| `prompt` | String | Full prompt text |
| `response` | String | Full response text |
| `call_type` | String | e.g., `"analysis"`, `"classification"` |
| `latency_ms` | Float | Round-trip latency |
| `tokens_used` | Integer | Total tokens consumed |
| `cost_usd` | Float | Estimated cost |
| `related_market` | String (nullable) | Market ticker this analysis was for |
| `success` | Boolean | Whether the call succeeded |
| `error` | String (nullable) | Error message if failed |

### Table: `scan_logs` (model: `ScanRecord`)

Audit record of each automated scan cycle.

| Column | Type | Description |
|---|---|---|
| `id` | Integer PK | Auto-increment |
| `run_id` | String (unique) | UUID for this run |
| `started_at` | DateTime | Cycle start time |
| `completed_at` | DateTime (nullable) | Cycle end time |
| `categories_scanned` | JSON | e.g., `["btc", "weather"]` |
| `platforms_scanned` | JSON | e.g., `["polymarket", "kalshi"]` |
| `markets_found` | Integer | Total markets fetched |
| `signals_generated` | Integer | Signals computed |
| `trades_executed` | Integer | Positions opened |
| `ai_calls_made` | Integer | LLM calls this cycle |
| `ai_cost_usd` | Float | LLM cost this cycle |
| `success` | Boolean | Whether cycle completed without error |
| `error` | String (nullable) | Error message if failed |

### Table: `btc_price_snapshots` (model: `PriceSnapshot`)

Cache of price observations for momentum calculations.

| Column | Type |
|---|---|
| `id` | Integer PK |
| `timestamp` | DateTime |
| `price` | Float |
| `source` | String |

### Schema Migration

On startup, `migrate_schema()` inspects existing columns and runs raw `ALTER TABLE ... ADD COLUMN` statements for any columns added in newer versions of the codebase. This provides forward compatibility without a migration framework.

---

## 6. Backend: FastAPI Application

### Application Bootstrap (`backend/server/app.py`)

The FastAPI app is instantiated with:
- CORS middleware allowing all origins (suitable for development; restrict in production)
- Pydantic-validated response models (`response_model=...`) on all endpoints

On the `@app.on_event("startup")` hook:
1. `bootstrap_db()` — creates all tables + runs migrations
2. Checks for existing `PortfolioState` row; creates one with `INITIAL_BANKROLL` if none exists, or reloads and sets `is_running = True`
3. Calls `launch_automation()` from the orchestrator — starts APScheduler with all background jobs
4. Calls `record_activity("success", ...)` to log the startup event

On `@app.on_event("shutdown")`: calls `halt_automation()` to cleanly stop the scheduler.

### WebSocket Hub

A `SocketHub` class maintains a list of active WebSocket connections. It provides:
- `connect(ws)` — accepts and registers a connection
- `disconnect(ws)` — removes a connection
- `broadcast(payload)` — sends JSON to all connected clients (fire-and-forget, ignores errors)

The hub instance `_hub` is module-level and shared across all requests.

### Pydantic DTOs

All API responses are typed with Pydantic models. Key DTOs:

**`DashboardDTO`** — the combined response for `/api/dashboard`:
```python
class DashboardDTO(BaseModel):
    stats: PortfolioDTO               # Bankroll, win rate, P&L, is_running
    btc_price: Optional[PriceDTO]     # Current BTC price + changes
    microstructure: Optional[TechDTO] # RSI, momentum, VWAP, SMA, volatility
    windows: List[WindowDTO]          # Active BTC 5-min prediction windows
    active_signals: List[OpportunityDTO]  # All generated BTC signals
    recent_trades: List[PositionDTO]  # Last 50 trades
    equity_curve: List[dict]          # [{timestamp, pnl, bankroll}] total curve
    equity_by_strategy: dict          # {"1": [...], "2": [...], "3": [...]}
    equity_by_strategy_platform: dict # {"1": {"kalshi": [...], "polymarket": [...]}, ...}
    calibration: Optional[CalSummaryDTO]  # Model accuracy metrics
    weather_signals: List[WxSignalDTO]    # Weather trading signals
    weather_forecasts: List[WxForecastDTO] # Ensemble forecast summaries
```

**`OpportunityDTO`** — a BTC trading signal:
```python
class OpportunityDTO(BaseModel):
    market_ticker: str          # Polymarket market ID
    market_title: str           # Human-readable title
    platform: str               # "polymarket"
    direction: str              # "up" or "down"
    model_probability: float    # Our model's P(up)
    market_probability: float   # Market's implied P(up)
    edge: float                 # model_probability - market_probability
    confidence: float           # [0, 1] signal confidence
    suggested_size: float       # Kelly-sized stake in USD
    reasoning: str              # Full reasoning string with all indicator values
    timestamp: datetime
    category: str               # "crypto"
    event_slug: Optional[str]   # For settlement lookup
    btc_price: float            # BTC price at signal time
    btc_change_24h: float       # Approximate 24h change
    window_end: Optional[datetime]  # When the 5-min window closes
    actionable: bool            # True if edge >= MIN_EDGE_THRESHOLD
```

---

## 7. REST API Reference

All endpoints are prefixed with `/api/`. The frontend configures the base URL via `VITE_API_URL` env var (defaults to `http://localhost:8000`).

### Portfolio & Stats

| Method | Path | Description | Response |
|---|---|---|---|
| GET | `/api/stats` | Portfolio summary | `PortfolioDTO` |
| GET | `/api/equity-curve` | Cumulative P&L timeline | `[{timestamp, pnl, bankroll, trade_id}]` |
| GET | `/api/calibration` | Model accuracy by prediction bucket | `{buckets: CalBucketDTO[], summary: CalSummaryDTO}` |

### BTC Markets

| Method | Path | Description | Response |
|---|---|---|---|
| GET | `/api/btc/price` | Current BTC spot price | `PriceDTO` |
| GET | `/api/btc/windows` | Active 5-min prediction windows | `WindowDTO[]` |
| GET | `/api/signals` | All generated BTC signals (calls `evaluate_markets()` live) | `OpportunityDTO[]` |
| GET | `/api/signals/actionable` | BTC signals filtered to edge >= threshold | `OpportunityDTO[]` |

### Trade Management

| Method | Path | Description | Response |
|---|---|---|---|
| GET | `/api/trades?limit=50&status=win` | Trade history (filterable) | `PositionDTO[]` |
| POST | `/api/simulate-trade?signal_ticker=X` | Manually open a position for a given signal | `{status, trade_id, size}` |
| POST | `/api/run-scan` | Trigger a manual BTC + weather scan | `{total_signals, actionable_signals, weather_signals, weather_actionable}` |
| POST | `/api/settle-trades` | Trigger a manual settlement check | `{status, settled_count, trades: [{id, result, pnl}]}` |

### Bot Control

| Method | Path | Description |
|---|---|---|
| POST | `/api/bot/start` | Enable automated trading, (re)start scheduler |
| POST | `/api/bot/stop` | Pause trading (scheduler keeps running; no new trades) |
| POST | `/api/bot/reset` | Delete all positions + LLM logs, reset bankroll to INITIAL_BANKROLL |

### Weather

| Method | Path | Description |
|---|---|---|
| GET | `/api/weather/forecasts` | Ensemble forecast summaries per city |
| GET | `/api/weather/markets` | Available weather temperature contracts |
| GET | `/api/weather/signals` | Generated weather trading signals |

### Other

| Method | Path | Description |
|---|---|---|
| GET | `/` | Health check + version |
| GET | `/api/health` | `{"status": "healthy"}` |
| GET | `/api/kalshi/status` | Kalshi connection check + balance |
| GET | `/api/events?limit=50` | Recent activity log entries |
| GET | `/api/dashboard` | **All data in one call** — used by the frontend |

### Calibration Data Structure

The `/api/calibration` endpoint bins settled signals into 5% probability buckets:
```json
{
  "buckets": [
    {
      "bucket": "50-55%",
      "predicted_avg": 0.523,
      "actual_rate": 0.61,
      "count": 18
    }
  ],
  "summary": {
    "total_signals": 450,
    "total_with_outcome": 120,
    "accuracy": 0.58,
    "avg_predicted_edge": 0.047,
    "avg_actual_edge": 0.031,
    "brier_score": 0.24
  }
}
```

The Brier score is computed as `mean((model_probability - settlement_value)^2)` across all settled signals.

---

## 8. WebSocket API

### Endpoint: `WS /ws/events`

On connection:
1. Server accepts the WebSocket and registers it with `SocketHub`
2. Immediately sends a welcome event
3. Replays the last 20 activity log entries so the client has immediate context
4. Enters an infinite loop:
   - Every 2 seconds, checks if new activity entries have appeared since last send
   - Sends any new entries as JSON objects
   - Sends a heartbeat message every loop

**Event JSON format:**
```json
{
  "timestamp": "2025-05-12T14:32:01.123456",
  "type": "trade",
  "message": "BTC UP $45 @ 43% | btc-5min-up-1715...abc",
  "data": {
    "slug": "btc-5min-up-1715...",
    "direction": "up",
    "size": 45,
    "edge": 0.087,
    "entry_price": 0.43,
    "btc_price": 62450.0
  }
}
```

**Event types:**
- `"info"` — informational log entry
- `"data"` — scan result data (signal counts, etc.)
- `"trade"` — a position was opened or closed
- `"success"` — positive outcome (startup, settlement, etc.)
- `"warning"` — risk limit hit, data quality issue
- `"error"` — exception caught
- `"heartbeat"` — keepalive pulse

On `WebSocketDisconnect`, the connection is removed from the hub.

---

## 9. Background Scheduler (Orchestrator)

`backend/engine/orchestrator.py` manages all automated background work using **APScheduler**'s `AsyncIOScheduler`. All scheduled functions are `async def` coroutines running within the app's asyncio event loop.

### Activity Log

An in-memory list `_activity_log` (max 200 entries, FIFO) stores activity dicts that the WebSocket streams to clients and the `/api/events` endpoint serves. `record_activity(type, message, data)` is called throughout the codebase to append entries.

### Scheduled Jobs

| Job ID | Function | Default Interval | Condition |
|---|---|---|---|
| `market_scan` | `crypto_cycle()` | 60 seconds | `BTC_ENABLED=true` |
| `settlement_check` | `resolution_cycle()` | 120 seconds | Always |
| `heartbeat` | `pulse_check()` | 60 seconds | Always |
| `weather_scan` | `wx_cycle()` | 300 seconds | `WEATHER_ENABLED=true` |
| `weather_s2_exit` | `wx_exit_cycle()` | 10 minutes | `WEATHER_ENABLED=true` |

All jobs have `max_instances=1` to prevent overlap. On launch, `crypto_cycle()` and `wx_cycle()` are immediately triggered via `asyncio.create_task()` so there's no delay before the first scan.

### `crypto_cycle()` — BTC Trade Execution

```
1. Call evaluate_markets() → list of MarketOpportunity
2. Filter to viable (edge >= threshold)
3. Check bot.is_running — skip if paused
4. Check daily loss circuit breaker (sum of today's settled PnL)
5. Check pending count < MAX_TOTAL_PENDING_TRADES
6. For each viable opportunity (up to MAX_PER_SCAN=2):
   a. Check no existing unsettled position for same event_slug
   b. Compute pos_size = min(suggested_size, bankroll * 3%, MAX_TRADE_SIZE)
   c. Ensure pos_size >= MIN_SIZE ($10)
   d. Create Position record (settled=False)
   e. Link to most recent unexecuted Opportunity for this ticker
   f. portfolio.total_trades += 1
   g. record_activity("trade", ...)
7. Commit all changes in one transaction
```

### `wx_cycle()` — Weather Trade Execution

```
1. Call evaluate_wx_markets() → list of WxOpportunity
2. Deduplicate by (city_key, target_date, metric) — keep highest edge per city+date+metric
3. Split into viable_s1 (edge >= 8%) and viable_s3 (edge >= 15%)
4. For each S1 opportunity (up to 3):
   a. Open two positions: strategy=1 and strategy=2 (same entry, same size)
   b. Size = BASE_UNIT ($75)
5. For each S3 opportunity (up to 3):
   a. Open one position: strategy=3
   b. Size = compute_strategy_3_size(edge) — tiered: 1/2/5 units
6. Commit all changes
```

### `wx_exit_cycle()` — Strategy 2 Early Exit (runs every 10 min)

Checks all open Strategy 2 weather positions for early exit conditions:
```
For each unsettled S2 position:
  - Skip if entry_price >= 50¢ (hold to settlement)
  - Skip if entry_price >= 45¢ (not a low-conviction entry)
  - Calculate hours_remaining until end-of-day settlement (~23:59 UTC)
  - Skip if hours_remaining < 2 (too close to settle, let it ride)
  - Skip if hours_remaining < 4 (minimum time required for exit logic)
  - Fetch current market price from Polymarket API
  - If current_price >= model_fair_value (edge has closed):
      → Settle the position immediately with current price as exit value
      → PnL = (current_price - entry_price) * size
      → record_activity("trade", "WX S2 EARLY EXIT ...")
```

### `resolution_cycle()` — Settlement Check

```
1. Query all unsettled positions (settled=False)
2. For each position:
   - If market_type="weather": call evaluate_wx_position()
   - Else: call evaluate_position_outcome()
3. For resolved positions:
   - Set settled=True, settlement_value, pnl, settlement_time, result
   - Update linked Opportunity with actual_outcome, outcome_correct
4. Commit batch
5. Call sync_portfolio() to update bankroll and win count
```

### `pulse_check()` — Heartbeat (every 60s)

Logs current bankroll and pending trade count. Used for health monitoring.

---

## 10. BTC Analysis Engine

`backend/engine/analysis.py`

### `evaluate_markets() → List[MarketOpportunity]`

Top-level function called by the scan cycle and API endpoints.

```
1. Load active BTC windows from Polymarket: load_active_windows()
2. For each window, call assess_window(window) with 0.1s delay between calls
3. Sort results by |edge| descending
4. Persist all non-zero-edge opportunities to the signals table
5. Return full list
```

### `assess_window(window: CryptoWindow) → Optional[MarketOpportunity]`

The core signal generation function.

**Step 1: Fetch Technicals**
```python
tech = await snapshot_technicals()  # From price_feed.py
```
Returns `None` if price feed is unavailable.

**Step 2: Basic Market Sanity**
```python
if mkt_up_prob < 0.02 or mkt_up_prob > 0.98:
    return None  # Extreme markets are likely already resolved
```

**Step 3: Individual Technical Signals**

Each signal is normalized to `[-1.0, 1.0]` where positive = bullish (up):

**RSI Signal** (mean-reversion):
```
RSI < 30: rsi_sig = 0.5 + (30 - RSI) / 30  # Oversold → long signal
RSI > 70: rsi_sig = -0.5 - (RSI - 70) / 30  # Overbought → short signal
RSI < 45: rsi_sig = (45 - RSI) / 30          # Mild oversold
RSI > 55: rsi_sig = -(RSI - 55) / 30         # Mild overbought
45 ≤ RSI ≤ 55: rsi_sig = 0.0                 # Neutral
```

**Momentum Signal** (trend-following):
```
mom_blend = momentum_1m * 0.50 + momentum_5m * 0.35 + momentum_15m * 0.15
mom_sig = clamp(mom_blend / 0.10, -1.0, 1.0)
```
(Positive momentum → positive signal)

**VWAP Deviation Signal** (mean-reversion from volume-weighted average):
```
vwap_sig = clamp(vwap_deviation / 0.05, -1.0, 1.0)
```
(Price above VWAP → positive = up signal, assuming continuation)

**SMA Crossover Signal**:
```
sma_cross = (SMA5 - SMA15) / price * 100
sma_sig = clamp(sma_cross / 0.03, -1.0, 1.0)
```

**Market Skew Signal** (contrarian):
```
skew = up_price - 0.50        # How far market leans up
skew_sig = clamp(-skew * 4, -1.0, 1.0)  # If market leans up, we lean down
```

**Step 4: Convergence Filter**
```
up_count = count of indicators > 0.05
down_count = count of indicators < -0.05
converged = (up_count >= 2) OR (down_count >= 2)
```
Requires at least 2 of the 4 directional indicators (RSI, momentum, VWAP, SMA) to agree. The market skew signal is excluded from this count (it's a separate contrarian overlay).

**Step 5: Weighted Composite**
```
composite = rsi_sig * 0.20
          + mom_sig * 0.35
          + vwap_sig * 0.20
          + sma_sig * 0.15
          + skew_sig * 0.10

model_up_probability = clamp(0.50 + composite * 0.15, 0.35, 0.65)
```
The model probability is bounded to `[0.35, 0.65]` — the bot never predicts extreme certainty. The `composite * 0.15` factor means a maximum composite of ±1.0 only shifts the probability by ±15% from 50%.

**Step 6: Edge Calculation**
```python
def compute_advantage(model_prob, market_price):
    up_adv = model_prob - market_price
    down_adv = (1 - model_prob) - (1 - market_price)
    if up_adv >= down_adv:
        return up_adv, "up"
    else:
        return down_adv, "down"
```
Returns the direction with the highest edge.

**Step 7: Filter Gate**

All three conditions must pass, or edge is forced to 0:
- `converged` — 2+ indicators agree
- `entry_price <= MAX_ENTRY_PRICE` (≤ 55¢)
- `MIN_TIME_REMAINING <= time_remaining <= MAX_TIME_REMAINING` (60–1800 seconds)

**Step 8: Kelly Position Sizing**
```python
def optimal_stake(edge, probability, market_price, direction, bankroll):
    odds = (1 - px) / px          # Decimal odds (what you win per $1 risked)
    kelly = (win_p * odds - lose_p) / odds  # Full Kelly fraction
    kelly *= KELLY_FRACTION         # Scale to 15% of full Kelly
    kelly = min(kelly, 0.05)        # Hard cap at 5% of bankroll
    kelly = max(kelly, 0)
    stake = kelly * bankroll
    stake = min(stake, MAX_TRADE_SIZE)  # Hard cap at $75
    return stake
```

**Step 9: Confidence Score**
```
vol_factor = min(1.0, volatility / 0.05)
convergence_str = max(up_count, down_count) / 4.0
confidence = min(0.8, 0.3 + convergence_str * 0.3 + |composite| * 0.2) * vol_factor
```

**Step 10: Reasoning String**

Every opportunity carries a full text explanation:
```
[ACTIONABLE] BTC $62450 | RSI:42 Mom1m:+0.021% Mom5m:+0.043% VWAP:-0.012% 
SMA:+0.0021% Vol:0.0312% | Composite:+0.287 -> Model UP:55% vs Mkt:48% | 
Edge:+7.0% -> UP @ 48% | Convergence:3/4 | Window ends: 14:35 UTC
```

---

## 11. Weather Analysis Engine

`backend/engine/wx_analysis.py`

### Data Model: `WxOpportunity`

Similar to `MarketOpportunity` but adds:
- `ensemble_mean` — mean forecast high/low temperature
- `ensemble_std` — standard deviation across ensemble members
- `ensemble_members` — count of ensemble members used

### `evaluate_wx_markets() → List[WxOpportunity]`

```
1. Fetch weather contracts from Polymarket (if enabled) and Kalshi (if configured)
2. Load ensemble forecasts for each configured city
3. For each contract:
   a. Match to city's ensemble forecast
   b. Compute model probability
   c. Calculate edge vs. market price
   d. Size with flat unit-based scheme (Kelly not used here)
4. Sort by |edge| descending
5. Persist signals to DB
6. Return all signals
```

### Probability Computation for Temperature Contracts

**Threshold contracts** (e.g., "High temperature above 75°F in NYC"):
```
model_yes_prob = (ensemble members where forecast > threshold) / total_members
```

**Range contracts** (e.g., "High temperature between 70-75°F in NYC"):
```
model_yes_prob = (ensemble members where lower < forecast < upper) / total_members
```

**Edge calculation:**
```
edge = model_yes_prob - market_yes_price
if edge > 0: direction = "yes"
else: direction = "no", edge = (1 - model_yes_prob) - market_no_price
```

**Confidence:**
```
confidence = max(model_yes_prob, 1 - model_yes_prob)  # Ensemble agreement ratio
```

---

## 12. Weather Trading Strategies

`backend/engine/wx_strategies.py`

Three strategies run in parallel on every weather scan. Each opened position is tagged with its `strategy` ID.

### Strategy 1: Baseline

- **Entry threshold:** `|edge| >= 8%` (WEATHER_MIN_EDGE_THRESHOLD)
- **Position size:** 1 unit = `$75`
- **Exit:** Hold to settlement (contract expires at end of target day)
- **Logic:** Simple edge-based entry; let the market resolve

### Strategy 2: Managed Exit (same entry as S1)

- **Entry threshold:** Same as Strategy 1 (same trade is opened simultaneously)
- **Position size:** 1 unit = `$75`
- **Early exit logic** (checked every 10 minutes by `wx_exit_cycle`):
  ```
  Skip if entry_price >= $0.50  (confident entry, hold)
  Skip if entry_price >= $0.45  (not a low-conviction entry)
  Skip if hours_remaining < 2   (too close to settle)
  Skip if hours_remaining < 4   (minimum exit window)
  Fetch current market price
  Exit early if current_price >= model_fair_value (edge has closed)
  PnL = (current_price - entry_price) × size
  ```
- **Intent:** Capture profits when the market re-prices toward our model estimate before settlement, especially for low-conviction entries

### Strategy 3: High-Edge Only

- **Entry threshold:** `|edge| >= 15%`
- **Position sizing — tiered by edge:**
  | Edge | Units | Dollar Size |
  |---|---|---|
  | 15–24% | 1 unit | $75 |
  | 25–34% | 2 units | $150 |
  | 35%+ | 5 units | $375 |
- **Exit:** Hold to settlement
- **Logic:** Only enter on high-conviction signals; scale in more aggressively

### Deduplication

Before executing, the scan deduplicates by `(city_key, target_date, metric)` — keeping only the highest-edge opportunity per combination. This prevents correlated bets where multiple contracts (e.g., "above 70°F" and "above 72°F") for the same city/date/temperature are driven by the same underlying forecast.

---

## 13. Settlement & Resolution Engine

`backend/engine/resolution.py`

### BTC Position Settlement: `evaluate_position_outcome(pos)`

```
1. Call check_polymarket_outcome(market_id, event_slug)
2. check_polymarket_outcome:
   a. Try fetching event by slug from Gamma API: GET /events?slug=...
   b. If not found, try: GET /markets/{market_id}
   c. If 404, search all events (closed and open) looking for the market ID
3. _interpret_outcome(market_data):
   - If market.closed == False → not resolved
   - Parse outcomePrices array
   - If prices[0] > 0.99 → UP/YES won (settlement_value = 1.0)
   - If prices[0] < 0.01 → DOWN/NO won (settlement_value = 0.0)
   - Otherwise → not yet resolved
```

### Weather Position Settlement: `evaluate_wx_position(pos)`

Routes by platform:
- `platform = "kalshi"`: calls `_check_kalshi_outcome(ticker)` — checks Kalshi's market status/result fields
- `platform = "polymarket"`: same flow as BTC settlement

### P&L Calculation: `compute_return(pos, settlement_val)`

Prediction market binary payoff model:
```
If direction = "yes":
    Win (settlement_val = 1.0):  pnl = size × (1.0 - entry_price)
    Loss (settlement_val = 0.0): pnl = -size × entry_price

If direction = "no":
    Win (settlement_val = 0.0):  pnl = size × (1.0 - entry_price)
    Loss (settlement_val = 1.0): pnl = -size × entry_price
```

For a $75 bet at 43¢:
- Win: `$75 × (1.0 - 0.43) = $42.75`
- Loss: `-$75 × 0.43 = -$32.25`

### Portfolio Sync: `sync_portfolio(session, resolved)`

After settling a batch, iterates resolved positions:
```
portfolio.total_pnl += pos.pnl
portfolio.bankroll += pos.pnl
if pos.result == "win": portfolio.winning_trades += 1
```

### Calibration Update

When a position settles, its linked `Opportunity` record is updated:
```
linked.actual_outcome = "up" if settlement_val == 1.0 else "down"
linked.outcome_correct = (linked.direction == actual_outcome)
linked.settlement_value = settlement_val
linked.settled_at = now
```

This data feeds the calibration panel.

---

## 14. External Data Sources

### BTC Price Feed (`backend/sources/price_feed.py`)

**`snapshot_technicals() → TechnicalSnapshot`**

Fetches 60 one-minute OHLCV candles via a cascade:
1. **Coinbase** (`GET /products/BTC-USD/candles?granularity=60&start=...&end=...`)
2. **Kraken** (`GET /0/public/OHLC?pair=XBTUSD&interval=1`)
3. **Binance** (`GET /api/v3/klines?symbol=BTCUSDT&interval=1m&limit=60`)
4. **Bybit** (`GET /v5/market/kline?category=spot&symbol=BTCUSDT&interval=1&limit=60`)

Results are cached for 30 seconds (`_CANDLE_TTL`).

Computed indicators from candle data:
- **RSI (14-period, Wilder's):** Uses exponential smoothing for gains/losses
- **Momentum:** `(close[-n] - close[-n-1]) / close[-n-1] * 100` for n = 1, 5, 15
- **VWAP** (30-bar): `sum(typical_price × volume) / sum(volume)` where `typical = (H + L + C) / 3`
- **VWAP deviation:** `(price - vwap) / vwap * 100`
- **SMA crossover:** `(SMA5 - SMA15) / price * 100`
- **Volatility:** Standard deviation of 30 one-minute returns × 100

**`get_spot_price(symbol) → SpotQuote`**

Fetches from CoinGecko's `/coins/{id}` endpoint. Returns current price + 24h/7d changes. Used for the dashboard's BTC price card.

### Polymarket BTC Source (`backend/sources/polymarket_btc.py`)

**`load_active_windows() → List[CryptoWindow]`**

Queries the Polymarket Gamma API for BTC 5-minute prediction events:
```
GET https://gamma-api.polymarket.com/events?tag=bitcoin&closed=false
```
Parses events looking for markets where the title matches "BTC 5-minute" patterns. For each matching market, creates a `CryptoWindow` with:
- `slug` — event slug for settlement lookups
- `market_id` — individual market ID
- `up_price` / `down_price` — current best prices for up/down outcomes
- `window_start` / `window_end` — timestamps of the prediction window
- `volume` — total market volume
- `is_active` / `is_upcoming` — whether window is currently active
- `time_until_end` — seconds remaining
- `spread` — up_price + down_price - 1.0 (market maker spread)

### Polymarket Weather Source (`backend/sources/polymarket_weather.py`)

**`load_poly_temp_contracts(city_keys) → List[WxContract]`**

Searches Polymarket events for temperature contracts matching configured cities. Uses title parsing (via Groq LLM if available, otherwise regex) to extract:
- City name
- Target date
- Temperature threshold
- Metric (high vs. low)
- Direction (above/below)

Returns `WxContract` objects with yes/no prices.

### Kalshi API (`backend/sources/kalshi_api.py`)

**Authentication:**
Kalshi uses RSA-PSS signing. Each request is signed with:
```
timestamp = current Unix milliseconds
msg = f"{timestamp}GET/trade-api/v2/markets/{ticker}"
signature = rsa_pss_sign(private_key, msg.encode())
headers = {
    "KALSHI-ACCESS-KEY": KEY_ID,
    "KALSHI-ACCESS-TIMESTAMP": timestamp,
    "KALSHI-ACCESS-SIGNATURE": base64(signature)
}
```

Key methods:
- `get_market(ticker)` — fetch single market data
- `get_balance()` — fetch account balance
- `kalshi_configured()` — returns False if credentials are missing

### Kalshi Weather Source (`backend/sources/kalshi_weather.py`)

**`load_kalshi_temp_contracts(city_keys) → List[WxContract]`**

Queries Kalshi's markets API for temperature series:
```
GET /trade-api/v2/markets?series_ticker=HIGHTEMP-...&status=open
```
Maps Kalshi markets to the same `WxContract` format as Polymarket, normalizing city names and date parsing.

### Ensemble Weather Forecast (`backend/sources/ensemble_forecast.py`)

**`load_ensemble(city_key) → EnsembleForecast`**

**Station Registry:** Maps city keys to coordinates + NWS station IDs:
```python
STATION_REGISTRY = {
    "nyc": {"lat": 40.7128, "lon": -74.0060, "name": "New York City", "nws_station": "KNYC"},
    "chicago": {"lat": 41.8781, "lon": -87.6298, "name": "Chicago", "nws_station": "KORD"},
    "miami": {"lat": 25.7617, "lon": -80.1918, "name": "Miami", "nws_station": "KMIA"},
    "los_angeles": {"lat": 34.0522, "lon": -118.2437, "name": "Los Angeles", "nws_station": "KLAX"},
    "denver": {"lat": 39.7392, "lon": -104.9903, "name": "Denver", "nws_station": "KDEN"},
}
```

**Open-Meteo call:**
```
GET https://ensemble-api.open-meteo.com/v1/ensemble
    ?latitude=40.7128&longitude=-74.0060
    &daily=temperature_2m_max,temperature_2m_min
    &temperature_unit=fahrenheit
    &models=gfs_seamless,ecmwf_ifs04,gem_global,...
```

Returns hourly data for 20+ ensemble members. The code extracts the tomorrow's max/min forecast for each model member, then computes:
- `mean_high` / `mean_low` — ensemble mean
- `std_high` / `std_low` — ensemble standard deviation  
- `num_members` — count of members with valid data
- `ensemble_agreement` — fraction of members on the majority side of the threshold

**NWS historical observations:**
Used to calibrate or cross-check ensemble forecasts via the NWS gridpoint API.

---

## 15. LLM Integration

Optional components for enhanced signal quality.

### Anthropic Claude (`backend/llm/anthropic_client.py`)

Used for deep analysis: anomaly detection, multi-factor market assessment. Called with structured prompts built in `backend/llm/types.py`. The model reads market context, recent price action, and ensemble data, then returns a structured JSON assessment.

### Groq / Llama (`backend/llm/groq_client.py`)

Used for fast, low-cost tasks:
- **Title parsing:** Extract city, date, threshold, metric from raw market titles
- **Classification:** Quickly categorize markets without full analysis

The `GROQ_MODEL` config defaults to `llama-3.1-8b-instant` (very fast and cheap).

### LLM Budget Tracking (`backend/llm/tracking.py`)

Before each LLM call, checks if today's spend (summed from `ai_logs`) has reached `AI_DAILY_BUDGET_USD`. Logs every call with latency, tokens, and estimated cost.

### LLM Prompt Strategy

Prompts are built as structured documents in `backend/llm/types.py` that include:
- Current market data (price, spread, volume)
- Technical indicator snapshot
- Ensemble forecast data (for weather)
- Historical context
- Response format specification (JSON output)

---

## 16. Frontend Architecture

### Entry Point (`frontend/src/main.tsx`)

```tsx
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5000, retry: 2 }
  }
})

createRoot(document.getElementById('root')).render(
  <QueryClientProvider client={queryClient}>
    <App />
  </QueryClientProvider>
)
```

### Root Component (`frontend/src/App.tsx`)

The `App` component owns:
- A single `useQuery` polling `/api/dashboard` every 10 seconds
- Bot control mutations: `runScan`, `startBot`, `stopBot`
- Layout composition — a fixed header + main grid + footer

**Layout structure:**
```
┌─────────────────────────────────────────────────┐
│ HEADER: Title | Status | StatsCards | Controls  │
├───────────────────────────────┬─────────────────┤
│                               │                 │
│  Equity Chart (45% height)    │  Trades Table   │
│                               │  (full height,  │
├────────────┬──────────┬───────┤  scrollable)    │
│  Weather   │  System  │ Calib │                 │
│  Forecasts │  Log     │ Panel │                 │
│  Panel     │ Terminal │       │                 │
└────────────┴──────────┴───────┴─────────────────┘
│ FOOTER: data sources | refresh bar | status     │
└─────────────────────────────────────────────────┘
```

The main grid is `grid-cols-[1fr_340px]` — a wide left section and a fixed 340px trades column.

### API Client (`frontend/src/api.ts`)

Thin wrapper around axios. The base URL is `import.meta.env.VITE_API_URL` (defaults to `http://localhost:8000`). Every function is a typed async function returning the appropriate TypeScript type.

Key functions:
```typescript
fetchDashboard(): Promise<DashboardData>    // GET /api/dashboard
runScan(): Promise<ScanResult>              // POST /api/run-scan
startBot(): Promise<BotStatusResult>        // POST /api/bot/start
stopBot(): Promise<BotStatusResult>         // POST /api/bot/stop
resetBot(): Promise<ResetResult>            // POST /api/bot/reset
settleTradesApi(): Promise<SettleResult>    // POST /api/settle-trades
simulateTrade(ticker): Promise<TradeResult> // POST /api/simulate-trade?signal_ticker=...
fetchWeatherForecasts(): Promise<WeatherForecast[]>  // GET /api/weather/forecasts
fetchWeatherSignals(): Promise<WeatherSignal[]>      // GET /api/weather/signals
```

### Refresh Bar Component

A visual progress indicator that counts down the 10-second refresh interval. Implemented as a CSS width animation updated via `setInterval` every 1 second.

### Live Clock Component

Ticks every 1 second via `setInterval`, displays UTC wall clock time in the header.

---

## 17. Frontend Components

### `StatsCards.tsx`

Displays compact metric chips in the header:
- **P&L**: Color-coded (green/red), `+$123.45` format
- **Bankroll**: `$10.2K` abbreviated format
- **Win Rate**: percentage
- **Trade Count**: total trades

### `EquityChart.tsx`

Recharts `LineChart` with:
- X-axis: timestamps
- Y-axis: cumulative P&L in USD
- **Total equity curve** (main line)
- **Per-strategy curves** (Strategy 1/2/3) — can toggle
- **Per-platform curves** (Polymarket/Kalshi per strategy) — can toggle
- Tooltip shows exact P&L and bankroll at each data point
- Renders an empty/flat line if no data yet

### `TradesTable.tsx`

Scrollable table of recent positions (most recent first):
- Trade ID, market ticker (truncated)
- Direction badge (UP/DOWN with color)
- Entry price as percentage
- Size in USD
- Timestamp
- Strategy badge (S1/S2/S3)
- Result (WIN/LOSS/PENDING) with color coding
- P&L amount

### `Terminal.tsx`

A terminal-style scrolling log panel:
- Displays activity log from WebSocket or REST polling
- Each entry has color-coded type prefix: `[TRADE]`, `[INFO]`, `[ERROR]`, etc.
- Start/Stop/Scan buttons with loading states
- Shows bot status (Running/Idle), last scan time, quick stats

### `CalibrationPanel.tsx`

Displays model calibration data:
- **Summary metrics:** Brier score, accuracy, total signals, signals with outcomes
- **Calibration chart:** For each 5% probability bucket, shows predicted vs. actual win rate
- A perfectly calibrated model would show a diagonal line; deviations indicate over/under-confidence

### `WeatherPanel.tsx`

Two-section panel:
- **Forecast cards:** One per city showing ensemble mean high/low, standard deviation, ensemble agreement percentage
- **Signal list:** Weather trading signals with edge, direction, city, date, threshold, and model vs. market probability

### `MicrostructurePanel.tsx`

Real-time BTC technical indicator display:
- RSI bar (0-100 scale, color-coded by overbought/oversold zones)
- Momentum gauges (1m, 5m, 15m)
- VWAP deviation
- SMA crossover
- Volatility reading
- Current BTC price and data source

### `SignalsTable.tsx`

Tabular view of active BTC trading signals:
- Market slug, direction, edge, confidence, suggested size
- Highlights actionable signals (edge >= threshold) differently from filtered ones

---

## 18. End-to-End Data Flows

### Flow A: BTC Trade (Automated, every 60 seconds)

```
APScheduler triggers crypto_cycle()
    │
    ├── evaluate_markets()
    │       │
    │       ├── load_active_windows()
    │       │       └── GET gamma-api.polymarket.com/events?tag=bitcoin
    │       │           Parse response → List[CryptoWindow]
    │       │
    │       └── For each window: assess_window(window)
    │               │
    │               ├── snapshot_technicals()
    │               │       └── retrieve_candles(60)
    │               │               └── GET coinbase.com/products/BTC-USD/candles
    │               │                   (fallback: Kraken → Binance → Bybit)
    │               │                   Cache result for 30s
    │               │           Compute RSI, momentum, VWAP, SMA, volatility
    │               │           Return TechnicalSnapshot
    │               │
    │               ├── Compute individual signals: rsi_sig, mom_sig, vwap_sig, sma_sig, skew_sig
    │               ├── Convergence check: 2+ indicators must agree
    │               ├── Weighted composite → model_up_probability [0.35, 0.65]
    │               ├── compute_advantage() → (edge, direction)
    │               ├── Apply filters: convergence + entry_price + time_remaining
    │               ├── optimal_stake() → Kelly-sized position size
    │               └── Return MarketOpportunity
    │
    ├── _store_opportunities() — persist all signals to signals table
    │
    ├── Filter viable = [o for o in opps if o.passes_threshold]
    ├── Check is_running, daily_loss_limit, pending_count
    │
    └── For each viable (up to 2):
            ├── Check no duplicate for same event_slug
            ├── Create Position record in DB
            ├── Link to Opportunity record (executed=True, signal_id=...)
            ├── portfolio.total_trades += 1
            ├── record_activity("trade", ...)
            └── session.commit()
```

### Flow B: Weather Trade (Automated, every 300 seconds)

```
APScheduler triggers wx_cycle()
    │
    ├── evaluate_wx_markets()
    │       │
    │       ├── load_poly_temp_contracts(city_keys)
    │       │       └── GET gamma-api.polymarket.com/events?tag=weather
    │       │           Parse/classify titles → List[WxContract]
    │       │
    │       ├── load_kalshi_temp_contracts(city_keys) [if kalshi enabled]
    │       │       └── GET trade-api.kalshi.com/v2/markets?series_ticker=HIGHTEMP-...
    │       │           → List[WxContract]
    │       │
    │       └── For each contract:
    │               ├── load_ensemble(city_key)
    │               │       └── GET ensemble-api.open-meteo.com/v1/ensemble
    │               │           Parse ensemble members → mean/std/agreement
    │               │
    │               ├── Count members above/below threshold
    │               ├── model_yes_prob = members_on_yes_side / total_members
    │               ├── edge = model_yes_prob - market_yes_price
    │               └── Return WxOpportunity
    │
    ├── Deduplicate by (city_key, target_date, metric)
    │
    ├── viable_s1 = [o for o if |edge| >= 8%]
    ├── viable_s3 = [o for o if |edge| >= 15%]
    │
    ├── For each S1 viable (up to 3):
    │       ├── Create Position(strategy=1, size=$75)
    │       └── Create Position(strategy=2, size=$75)  ← same trade, separate record
    │
    └── For each S3 viable (up to 3):
            └── Create Position(strategy=3, size=compute_strategy_3_size(edge))
```

### Flow C: Settlement Check (Automated, every 120 seconds)

```
APScheduler triggers resolution_cycle()
    │
    ├── Query all positions WHERE settled=False
    │
    └── For each position:
            │
            ├── [if market_type="btc"] evaluate_position_outcome(pos)
            │       ├── GET gamma-api.polymarket.com/events?slug={event_slug}
            │       ├── Parse market.closed and market.outcomePrices
            │       ├── If prices[0] > 0.99 → settlement_value=1.0 (UP won)
            │       ├── If prices[0] < 0.01 → settlement_value=0.0 (DOWN won)
            │       └── compute_return(pos, settlement_value) → pnl
            │
            ├── [if market_type="weather"] evaluate_wx_position(pos)
            │       ├── [kalshi] GET kalshi market status+result
            │       └── [polymarket] same as BTC flow
            │
            ├── If resolved:
            │       ├── pos.settled = True
            │       ├── pos.pnl = computed_pnl
            │       ├── pos.result = "win" | "loss" | "push"
            │       ├── linked_signal.outcome_correct = ...
            │       └── Append to resolved list
            │
            └── sync_portfolio(resolved):
                    ├── portfolio.bankroll += sum(pnl for resolved)
                    ├── portfolio.total_pnl += sum(pnl for resolved)
                    └── portfolio.winning_trades += count(result="win")
```

### Flow D: Dashboard Load (Frontend, every 10 seconds)

```
React Query calls fetchDashboard()
    │
    └── GET /api/dashboard
            │
            ├── portfolio_summary() → PortfolioDTO
            ├── snapshot_technicals() → TechDTO (TechnicalSnapshot)
            ├── get_spot_price("BTC") → PriceDTO (if technicals fail)
            ├── load_active_windows() → List[WindowDTO]
            ├── evaluate_markets() → List[OpportunityDTO]
            │
            ├── Query Position ORDER BY timestamp DESC LIMIT 50 → List[PositionDTO]
            │
            ├── Equity curve:
            │       Query settled positions ORDER BY timestamp
            │       Cumulative sum of pnl → [{timestamp, pnl, bankroll}]
            │
            ├── Per-strategy equity curves:
            │       For strategy in [1,2,3]:
            │           Filter settled by strategy
            │           Cumulative sum → equity_by_strategy["1"|"2"|"3"]
            │       For each strategy, split by platform:
            │           equity_by_strategy_platform["1"]["kalshi"|"polymarket"]
            │
            ├── _compute_cal_summary() → CalSummaryDTO
            │
            ├── evaluate_wx_markets() → List[WxSignalDTO]
            └── load_ensemble() for each city → List[WxForecastDTO]
```

### Flow E: WebSocket Live Feed

```
Frontend connects WS /ws/events
    │
    ├── Server accepts, registers in SocketHub
    ├── Server sends welcome message
    ├── Server replays last 20 activity entries
    │
    └── Server loop (every 2 seconds):
            ├── Check if new entries in _activity_log since last send
            ├── Push any new entries as JSON
            └── Push heartbeat
                    │
                    Frontend Terminal component displays in real-time
```

---

## 19. Risk Controls

### Position-Level Controls
- **Maximum entry price:** 55¢ for BTC, 70¢ for weather. Prevents buying into already-resolved or heavily one-sided markets.
- **Kelly fraction:** Only 15% of the full Kelly stake is used, dramatically reducing variance.
- **Hard cap per trade:** `MAX_TRADE_SIZE = $75` for BTC, `BASE_UNIT = $75` for weather.
- **Time filter:** BTC trades only entered with 60–1800 seconds remaining. Eliminates stale markets.
- **Convergence requirement:** At least 2/4 technical indicators must agree (BTC only).

### Portfolio-Level Controls
- **Daily loss limit:** If today's settled P&L ≤ −`DAILY_LOSS_LIMIT` ($300), `crypto_cycle` halts for the day.
- **Max pending trades:** If open positions ≥ `MAX_TOTAL_PENDING_TRADES` (20), no new trades open.
- **Max trades per scan:** BTC opens at most 2 positions per 60-second scan.
- **Max trades per weather scan:** At most 3 positions per strategy per 300-second scan.
- **Deduplication:** Won't open a duplicate position for the same market window (checked by event_slug).

### Simulation Mode
When `SIMULATION_MODE=true`, the execution logic still runs completely (positions created in DB, Kelly sizing computed, settlements tracked) but no real money is moved on external platforms. This is the default configuration.

---

## 20. Deployment

### Local Development

**Backend:**
```bash
pip install -r requirements.txt
cp .env.example .env
# Fill in .env with API keys
python run.py          # Starts uvicorn on 0.0.0.0:8000
```

`run.py` content:
```python
import uvicorn
from backend.server.app import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
```

**Frontend:**
```bash
cd frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev   # Vite dev server on port 5173
```

### Production (Railway)

`Procfile`:
```
web: python run.py
```

Environment variables are set in Railway's dashboard or injected from AWS Secrets Manager.

**Frontend:**
```bash
npm run build    # Produces dist/ directory
```
Deploy `dist/` to Vercel, Netlify, or any static host. Set `VITE_API_URL` to the Railway backend URL at build time.

`vercel.json`:
```json
{
  "rewrites": [{ "source": "/(.*)", "destination": "/" }]
}
```

### Database

For production, switch from SQLite to PostgreSQL:
```
DATABASE_URL=postgresql://user:pass@host:5432/tradingbot
```

SQLAlchemy handles both automatically. The `connect_args` for `check_same_thread` is only applied for SQLite.

### AWS Secrets Manager

Store a JSON bundle in Secrets Manager:
```json
{
  "GROQ_API_KEY": "gsk_...",
  "ANTHROPIC_API_KEY": "sk-ant-...",
  "KALSHI_API_KEY_ID": "...",
  "POLYMARKET_API_KEY": "..."
}
```

Set these environment variables on the host:
```
AWS_SECRET_NAME=trading-bot/api-keys
AWS_REGION=us-east-1
```
IAM role on the compute instance needs `secretsmanager:GetSecretValue` permission.

---

## Appendix: Key Formulas Reference

### Kelly Criterion (BTC)
```
odds = (1 - entry_price) / entry_price
kelly_full = (win_probability × odds - loss_probability) / odds
kelly_fraction = kelly_full × 0.15                    # 15% fractional Kelly
stake = min(kelly_fraction, 0.05) × bankroll          # Hard cap at 5% of bankroll
stake = min(stake, MAX_TRADE_SIZE)                    # Hard cap at $75
```

### Binary Market P&L
```
Long YES at entry_price p, size s:
  Win:  pnl = s × (1 - p)
  Loss: pnl = -s × p

Long NO at entry_price p, size s:
  Win:  pnl = s × (1 - p)
  Loss: pnl = -s × p
```

### Brier Score (Calibration)
```
Brier = (1/n) × Σ (model_probability_i - actual_outcome_i)²
where actual_outcome_i ∈ {0, 1}
Range: 0 (perfect) to 1 (worst possible)
```

### Weather Model Probability
```
model_yes_prob = count(ensemble_member_i where forecast_i > threshold) / N

For range contracts [L, U]:
model_yes_prob = count(ensemble_member_i where L < forecast_i < U) / N
```

### RSI (Wilder's Smoothing)
```
avg_gain[0] = mean(gains[0:14])
avg_loss[0] = mean(losses[0:14])
avg_gain[k] = (avg_gain[k-1] × 13 + gain[k]) / 14
avg_loss[k] = (avg_loss[k-1] × 13 + loss[k]) / 14
RS = avg_gain / avg_loss
RSI = 100 - 100 / (1 + RS)
```
