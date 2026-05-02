"""FastAPI application — routes and real-time WebSocket transport."""
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
import asyncio
import json
import os

from backend.env import cfg
from backend.storage.models import (
    db_session, bootstrap_db, DbSession,
    Opportunity, Position, PortfolioState, LLMLog, ScanRecord
)
from backend.engine.analysis import evaluate_markets, MarketOpportunity
from backend.sources.polymarket_btc import load_active_windows, CryptoWindow
from backend.sources.price_feed import get_spot_price, snapshot_technicals

from pydantic import BaseModel

app = FastAPI(
    title="BTC 5-Min Trading Bot",
    description="Polymarket BTC Up/Down 5-minute market trading bot",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SocketHub:
    def __init__(self):
        self._connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, payload: dict):
        for conn in self._connections:
            try:
                await conn.send_json(payload)
            except Exception:
                pass


_hub = SocketHub()


# ── Response DTOs ──────────────────────────────────────────────────────────────

class PriceDTO(BaseModel):
    price: float
    change_24h: float
    change_7d: float
    market_cap: float
    volume_24h: float
    last_updated: datetime


class WindowDTO(BaseModel):
    slug: str
    market_id: str
    up_price: float
    down_price: float
    window_start: datetime
    window_end: datetime
    volume: float
    is_active: bool
    is_upcoming: bool
    time_until_end: float
    spread: float


class TechDTO(BaseModel):
    rsi: float = 50.0
    momentum_1m: float = 0.0
    momentum_5m: float = 0.0
    momentum_15m: float = 0.0
    vwap_deviation: float = 0.0
    sma_crossover: float = 0.0
    volatility: float = 0.0
    price: float = 0.0
    source: str = "unknown"


class OpportunityDTO(BaseModel):
    market_ticker: str
    market_title: str
    platform: str
    direction: str
    model_probability: float
    market_probability: float
    edge: float
    confidence: float
    suggested_size: float
    reasoning: str
    timestamp: datetime
    category: str = "crypto"
    event_slug: Optional[str] = None
    btc_price: float = 0.0
    btc_change_24h: float = 0.0
    window_end: Optional[datetime] = None
    actionable: bool = False


class PositionDTO(BaseModel):
    id: int
    market_ticker: str
    platform: str
    event_slug: Optional[str] = None
    direction: str
    entry_price: float
    size: float
    timestamp: datetime
    settled: bool
    result: str
    pnl: Optional[float]
    strategy: int = 1
    edge_at_entry: Optional[float] = None


class PortfolioDTO(BaseModel):
    bankroll: float
    total_trades: int
    winning_trades: int
    win_rate: float
    total_pnl: float
    is_running: bool
    last_run: Optional[datetime]


class CalBucketDTO(BaseModel):
    bucket: str
    predicted_avg: float
    actual_rate: float
    count: int


class CalSummaryDTO(BaseModel):
    total_signals: int
    total_with_outcome: int
    accuracy: float
    avg_predicted_edge: float
    avg_actual_edge: float
    brier_score: float


class WxForecastDTO(BaseModel):
    city_key: str
    city_name: str
    target_date: str
    mean_high: float
    std_high: float
    mean_low: float
    std_low: float
    num_members: int
    ensemble_agreement: float


class WxMarketDTO(BaseModel):
    slug: str
    market_id: str
    platform: str = "polymarket"
    title: str
    city_key: str
    city_name: str
    target_date: str
    threshold_f: float
    metric: str
    direction: str
    yes_price: float
    no_price: float
    volume: float


class WxSignalDTO(BaseModel):
    market_id: str
    city_key: str
    city_name: str
    target_date: str
    threshold_f: float
    metric: str
    direction: str
    model_probability: float
    market_probability: float
    edge: float
    confidence: float
    suggested_size: float
    reasoning: str
    ensemble_mean: float
    ensemble_std: float
    ensemble_members: int
    actionable: bool = False


class DashboardDTO(BaseModel):
    stats: PortfolioDTO
    btc_price: Optional[PriceDTO]
    microstructure: Optional[TechDTO] = None
    windows: List[WindowDTO]
    active_signals: List[OpportunityDTO]
    recent_trades: List[PositionDTO]
    equity_curve: List[dict]
    equity_by_strategy: dict = {}
    calibration: Optional[CalSummaryDTO] = None
    weather_signals: List[WxSignalDTO] = []
    weather_forecasts: List[WxForecastDTO] = []


class ActivityDTO(BaseModel):
    timestamp: str
    type: str
    message: str
    data: dict = {}


# ── Lifecycle ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    print("=" * 60)
    print("BTC 5-MIN TRADING BOT v3.0")
    print("=" * 60)
    print("Initializing database...")

    bootstrap_db()

    session = DbSession()
    try:
        portfolio = session.query(PortfolioState).first()
        if not portfolio:
            portfolio = PortfolioState(
                bankroll=cfg.INITIAL_BANKROLL,
                total_trades=0,
                winning_trades=0,
                total_pnl=0.0,
                is_running=True
            )
            session.add(portfolio)
            session.commit()
            print(f"Created new bot state with ${cfg.INITIAL_BANKROLL:,.2f} bankroll")
        else:
            portfolio.is_running = True
            session.commit()
            print(f"Loaded bot state: Bankroll ${portfolio.bankroll:,.2f}, P&L ${portfolio.total_pnl:+,.2f}, {portfolio.total_trades} trades")
    finally:
        session.close()

    print("")
    print("Configuration:")
    print(f"  - Simulation mode: {cfg.SIMULATION_MODE}")
    print(f"  - Min edge threshold: {cfg.MIN_EDGE_THRESHOLD:.0%}")
    print(f"  - Kelly fraction: {cfg.KELLY_FRACTION:.0%}")
    print(f"  - Scan interval: {cfg.SCAN_INTERVAL_SECONDS}s")
    print(f"  - Settlement interval: {cfg.SETTLEMENT_INTERVAL_SECONDS}s")
    print("")

    from backend.engine.orchestrator import launch_automation, record_activity
    launch_automation()
    record_activity("success", "BTC 5-min trading bot initialized")

    print("Bot is now running!")
    print(f"  - BTC scan: every {cfg.SCAN_INTERVAL_SECONDS}s (edge >= {cfg.MIN_EDGE_THRESHOLD:.0%})")
    print(f"  - Settlement check: every {cfg.SETTLEMENT_INTERVAL_SECONDS}s")
    if cfg.WEATHER_ENABLED:
        print(f"  - Weather scan: every {cfg.WEATHER_SCAN_INTERVAL_SECONDS}s (edge >= {cfg.WEATHER_MIN_EDGE_THRESHOLD:.0%})")
        print(f"  - Weather cities: {cfg.WEATHER_CITIES}")
    else:
        print("  - Weather trading: DISABLED")
    print("=" * 60)


@app.on_event("shutdown")
async def shutdown():
    from backend.engine.orchestrator import halt_automation
    halt_automation()


# ── Core endpoints ─────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "message": "BTC 5-Min Trading Bot API v3.0", "simulation_mode": cfg.SIMULATION_MODE}


@app.get("/api/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/stats", response_model=PortfolioDTO)
async def portfolio_summary(session: Session = Depends(db_session)):
    portfolio = session.query(PortfolioState).first()
    if not portfolio:
        raise HTTPException(status_code=404, detail="Bot state not initialized")

    wr = portfolio.winning_trades / portfolio.total_trades if portfolio.total_trades > 0 else 0

    return PortfolioDTO(
        bankroll=portfolio.bankroll,
        total_trades=portfolio.total_trades,
        winning_trades=portfolio.winning_trades,
        win_rate=wr,
        total_pnl=portfolio.total_pnl,
        is_running=portfolio.is_running,
        last_run=portfolio.last_run
    )


@app.get("/api/btc/price", response_model=Optional[PriceDTO])
async def current_price():
    try:
        quote = await get_spot_price("BTC")
        if not quote:
            return None

        return PriceDTO(
            price=quote.current_price,
            change_24h=quote.change_24h,
            change_7d=quote.change_7d,
            market_cap=quote.market_cap,
            volume_24h=quote.volume_24h,
            last_updated=quote.last_updated
        )
    except Exception:
        return None


@app.get("/api/btc/windows", response_model=List[WindowDTO])
async def active_windows():
    try:
        windows = await load_active_windows()
        return [
            WindowDTO(
                slug=w.slug,
                market_id=w.market_id,
                up_price=w.up_price,
                down_price=w.down_price,
                window_start=w.window_start,
                window_end=w.window_end,
                volume=w.volume,
                is_active=w.is_active,
                is_upcoming=w.is_upcoming,
                time_until_end=w.time_until_end,
                spread=w.spread,
            )
            for w in windows
        ]
    except Exception:
        return []


@app.get("/api/signals", response_model=List[OpportunityDTO])
async def current_opportunities():
    try:
        opps = await evaluate_markets()
        return [_opp_to_dto(o) for o in opps]
    except Exception:
        return []


@app.get("/api/signals/actionable", response_model=List[OpportunityDTO])
async def viable_opportunities():
    try:
        opps = await evaluate_markets()
        viable = [o for o in opps if o.passes_threshold]
        return [_opp_to_dto(o) for o in viable]
    except Exception:
        return []


def _opp_to_dto(o: MarketOpportunity, actionable: bool = False) -> OpportunityDTO:
    return OpportunityDTO(
        market_ticker=o.market.market_id,
        market_title=f"BTC 5m - {o.market.slug}",
        platform="polymarket",
        direction=o.direction,
        model_probability=o.model_probability,
        market_probability=o.market_probability,
        edge=o.edge,
        confidence=o.confidence,
        suggested_size=o.suggested_size,
        reasoning=o.reasoning,
        timestamp=o.timestamp,
        category="crypto",
        event_slug=o.market.slug,
        btc_price=o.btc_price,
        btc_change_24h=o.btc_change_24h,
        window_end=o.market.window_end,
        actionable=actionable,
    )


@app.get("/api/trades", response_model=List[PositionDTO])
async def position_history(
    limit: int = 50,
    status: Optional[str] = None,
    session: Session = Depends(db_session)
):
    q = session.query(Position)
    if status:
        q = q.filter(Position.result == status)
    rows = q.order_by(Position.timestamp.desc()).limit(limit).all()

    return [
        PositionDTO(
            id=r.id,
            market_ticker=r.market_ticker,
            platform=r.platform,
            event_slug=r.event_slug,
            direction=r.direction,
            entry_price=r.entry_price,
            size=r.size,
            timestamp=r.timestamp,
            settled=r.settled,
            result=r.result,
            pnl=r.pnl
        )
        for r in rows
    ]


@app.get("/api/equity-curve")
async def equity_history(session: Session = Depends(db_session)):
    settled = session.query(Position).filter(Position.settled == True).order_by(Position.timestamp).all()

    curve = []
    cumulative = 0
    base = cfg.INITIAL_BANKROLL

    for pos in settled:
        if pos.pnl is not None:
            cumulative += pos.pnl
            curve.append({
                "timestamp": pos.timestamp.isoformat(),
                "pnl": cumulative,
                "bankroll": base + cumulative,
                "trade_id": pos.id
            })

    return curve


@app.post("/api/simulate-trade")
async def manual_position(signal_ticker: str, session: Session = Depends(db_session)):
    from backend.engine.orchestrator import record_activity

    opps = await evaluate_markets()
    match = next((o for o in opps if o.market.market_id == signal_ticker), None)

    if not match:
        raise HTTPException(status_code=404, detail="Signal not found")

    portfolio = session.query(PortfolioState).first()
    if not portfolio:
        raise HTTPException(status_code=500, detail="Bot state not initialized")

    entry_px = match.market.up_price if match.direction == "up" else match.market.down_price

    pos = Position(
        market_ticker=match.market.market_id,
        platform="polymarket",
        event_slug=match.market.slug,
        direction=match.direction,
        entry_price=entry_px,
        size=min(match.suggested_size, portfolio.bankroll * 0.05),
        model_probability=match.model_probability,
        market_price_at_entry=match.market_probability,
        edge_at_entry=match.edge
    )

    session.add(pos)
    portfolio.total_trades += 1
    session.commit()

    record_activity("trade", f"Manual BTC trade: {match.direction.upper()} {match.market.slug}")
    return {"status": "ok", "trade_id": pos.id, "size": pos.size}


@app.post("/api/run-scan")
async def run_scan(session: Session = Depends(db_session)):
    from backend.engine.orchestrator import trigger_scan, record_activity

    portfolio = session.query(PortfolioState).first()
    if portfolio:
        portfolio.last_run = datetime.utcnow()
        session.commit()

    record_activity("info", "Manual scan triggered (BTC + Weather)")
    await trigger_scan()

    opps = await evaluate_markets()
    viable = [o for o in opps if o.passes_threshold]

    result = {
        "status": "ok",
        "total_signals": len(opps),
        "actionable_signals": len(viable),
        "timestamp": datetime.utcnow().isoformat(),
    }

    if cfg.WEATHER_ENABLED:
        try:
            from backend.engine.wx_analysis import evaluate_wx_markets
            wx_opps = await evaluate_wx_markets()
            wx_viable = [o for o in wx_opps if o.passes_threshold]
            result["weather_signals"] = len(wx_opps)
            result["weather_actionable"] = len(wx_viable)
        except Exception:
            result["weather_signals"] = 0
            result["weather_actionable"] = 0

    return result


@app.post("/api/settle-trades")
async def settle_positions(session: Session = Depends(db_session)):
    from backend.engine.resolution import process_open_positions, sync_portfolio
    from backend.engine.orchestrator import record_activity

    record_activity("info", "Manual settlement triggered")

    resolved = await process_open_positions(session)
    await sync_portfolio(session, resolved)

    return {
        "status": "ok",
        "settled_count": len(resolved),
        "trades": [{"id": p.id, "result": p.result, "pnl": p.pnl} for p in resolved]
    }


def _compute_cal_summary(session: Session) -> Optional[CalSummaryDTO]:
    total = session.query(Opportunity).count()
    settled = session.query(Opportunity).filter(Opportunity.outcome_correct.isnot(None)).all()

    if not settled:
        if total == 0:
            return None
        return CalSummaryDTO(
            total_signals=total,
            total_with_outcome=0,
            accuracy=0.0,
            avg_predicted_edge=0.0,
            avg_actual_edge=0.0,
            brier_score=0.0,
        )

    n = len(settled)
    correct = sum(1 for s in settled if s.outcome_correct)
    accuracy = correct / n if n > 0 else 0.0

    avg_pred = sum(abs(s.edge) for s in settled) / n
    avg_actual = sum(
        abs(s.edge) if s.outcome_correct else -abs(s.edge)
        for s in settled
    ) / n

    brier = 0.0
    for s in settled:
        actual = s.settlement_value if s.settlement_value is not None else 0.5
        brier += (s.model_probability - actual) ** 2
    brier /= n

    return CalSummaryDTO(
        total_signals=total,
        total_with_outcome=n,
        accuracy=accuracy,
        avg_predicted_edge=avg_pred,
        avg_actual_edge=avg_actual,
        brier_score=brier,
    )


@app.get("/api/calibration")
async def calibration_data(session: Session = Depends(db_session)):
    settled = session.query(Opportunity).filter(Opportunity.outcome_correct.isnot(None)).all()

    if not settled:
        return {"buckets": [], "summary": None}

    from collections import defaultdict
    bins = defaultdict(lambda: {"predicted_sum": 0.0, "correct": 0, "total": 0})

    for s in settled:
        b_start = int(s.model_probability * 100 // 5) * 5
        b_end = b_start + 5
        key = f"{b_start}-{b_end}%"

        bins[key]["predicted_sum"] += s.model_probability
        bins[key]["total"] += 1
        if s.outcome_correct:
            bins[key]["correct"] += 1

    buckets = []
    for key in sorted(bins.keys()):
        d = bins[key]
        buckets.append(CalBucketDTO(
            bucket=key,
            predicted_avg=d["predicted_sum"] / d["total"],
            actual_rate=d["correct"] / d["total"],
            count=d["total"],
        ))

    summary = _compute_cal_summary(session)

    return {"buckets": buckets, "summary": summary}


# ── Kalshi status ──────────────────────────────────────────────────────────────

@app.get("/api/kalshi/status")
async def kalshi_connection_status():
    from backend.sources.kalshi_api import KalshiConnector, kalshi_configured

    if not kalshi_configured():
        return {
            "connected": False,
            "error": "Kalshi credentials not configured (KALSHI_API_KEY_ID / KALSHI_PRIVATE_KEY_PATH)",
        }

    try:
        connector = KalshiConnector()
        balance = await connector.get_balance()
        return {
            "connected": True,
            "balance": balance,
        }
    except Exception as exc:
        return {
            "connected": False,
            "error": str(exc),
        }


# ── Weather endpoints ──────────────────────────────────────────────────────────

@app.get("/api/weather/forecasts", response_model=List[WxForecastDTO])
async def weather_forecasts():
    if not cfg.WEATHER_ENABLED:
        return []

    try:
        from backend.sources.ensemble_forecast import load_ensemble, STATION_REGISTRY
        from datetime import date

        city_keys = [c.strip() for c in cfg.WEATHER_CITIES.split(",") if c.strip()]
        results = []

        for ck in city_keys:
            if ck not in STATION_REGISTRY:
                continue
            ensemble = await load_ensemble(ck)
            if ensemble:
                results.append(WxForecastDTO(
                    city_key=ensemble.city_key,
                    city_name=ensemble.city_name,
                    target_date=ensemble.target_date.isoformat(),
                    mean_high=ensemble.mean_high,
                    std_high=ensemble.std_high,
                    mean_low=ensemble.mean_low,
                    std_low=ensemble.std_low,
                    num_members=ensemble.num_members,
                    ensemble_agreement=ensemble.ensemble_agreement,
                ))

        return results
    except Exception:
        return []


@app.get("/api/weather/markets", response_model=List[WxMarketDTO])
async def weather_contracts():
    if not cfg.WEATHER_ENABLED:
        return []

    try:
        from backend.sources.polymarket_weather import load_poly_temp_contracts

        city_keys = [c.strip() for c in cfg.WEATHER_CITIES.split(",") if c.strip()]
        contracts = await load_poly_temp_contracts(city_keys)

        if cfg.KALSHI_ENABLED:
            try:
                from backend.sources.kalshi_api import kalshi_configured
                from backend.sources.kalshi_weather import load_kalshi_temp_contracts
                if kalshi_configured():
                    kalshi = await load_kalshi_temp_contracts(city_keys)
                    contracts.extend(kalshi)
            except Exception:
                pass

        return [
            WxMarketDTO(
                slug=c.slug,
                market_id=c.market_id,
                platform=c.platform,
                title=c.title,
                city_key=c.city_key,
                city_name=c.city_name,
                target_date=c.target_date.isoformat(),
                threshold_f=c.threshold_f,
                metric=c.metric,
                direction=c.direction,
                yes_price=c.yes_price,
                no_price=c.no_price,
                volume=c.volume,
            )
            for c in contracts
        ]
    except Exception:
        return []


@app.get("/api/weather/signals", response_model=List[WxSignalDTO])
async def weather_opportunities():
    if not cfg.WEATHER_ENABLED:
        return []

    try:
        from backend.engine.wx_analysis import evaluate_wx_markets

        opps = await evaluate_wx_markets()
        return [_wx_opp_to_dto(o) for o in opps]
    except Exception:
        return []


def _wx_opp_to_dto(o) -> WxSignalDTO:
    return WxSignalDTO(
        market_id=o.market.market_id,
        city_key=o.market.city_key,
        city_name=o.market.city_name,
        target_date=o.market.target_date.isoformat(),
        threshold_f=o.market.threshold_f,
        metric=o.market.metric,
        direction=o.direction,
        model_probability=o.model_probability,
        market_probability=o.market_probability,
        edge=o.edge,
        confidence=o.confidence,
        suggested_size=o.suggested_size,
        reasoning=o.reasoning,
        ensemble_mean=o.ensemble_mean,
        ensemble_std=o.ensemble_std,
        ensemble_members=o.ensemble_members,
        actionable=o.passes_threshold,
    )


@app.get("/api/events", response_model=List[ActivityDTO])
async def activity_feed(limit: int = 50):
    from backend.engine.orchestrator import recent_activities
    entries = recent_activities(limit)
    return [
        ActivityDTO(
            timestamp=e["timestamp"],
            type=e["type"],
            message=e["message"],
            data=e.get("data", {})
        )
        for e in entries
    ]


# ── Bot control ────────────────────────────────────────────────────────────────

@app.post("/api/bot/start")
async def start_trading(session: Session = Depends(db_session)):
    from backend.engine.orchestrator import launch_automation, record_activity, automation_active

    portfolio = session.query(PortfolioState).first()
    if portfolio:
        portfolio.is_running = True
        session.commit()

    if not automation_active():
        launch_automation()

    record_activity("success", "Trading bot started")
    return {"status": "started", "is_running": True}


@app.post("/api/bot/stop")
async def stop_trading(session: Session = Depends(db_session)):
    from backend.engine.orchestrator import record_activity

    portfolio = session.query(PortfolioState).first()
    if portfolio:
        portfolio.is_running = False
        session.commit()

    record_activity("info", "Trading bot paused")
    return {"status": "stopped", "is_running": False}


@app.post("/api/bot/reset")
async def reset_portfolio(session: Session = Depends(db_session)):
    from backend.engine.orchestrator import record_activity

    try:
        positions_cleared = session.query(Position).delete()
        portfolio = session.query(PortfolioState).first()
        if portfolio:
            portfolio.bankroll = cfg.INITIAL_BANKROLL
            portfolio.total_trades = 0
            portfolio.winning_trades = 0
            portfolio.total_pnl = 0.0
            portfolio.is_running = True

        logs_cleared = session.query(LLMLog).delete()
        session.commit()

        record_activity("success", f"Bot reset: {positions_cleared} trades deleted. Fresh start with ${cfg.INITIAL_BANKROLL:,.2f}")

        return {
            "status": "reset",
            "trades_deleted": positions_cleared,
            "ai_logs_deleted": logs_cleared,
            "new_bankroll": cfg.INITIAL_BANKROLL
        }

    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Reset failed: {exc}")


@app.get("/api/dashboard", response_model=DashboardDTO)
async def full_dashboard(session: Session = Depends(db_session)):
    stats = await portfolio_summary(session)

    price_data = None
    tech_data = None
    try:
        tech = await snapshot_technicals()
        if tech:
            tech_data = TechDTO(
                rsi=tech.rsi,
                momentum_1m=tech.momentum_1m,
                momentum_5m=tech.momentum_5m,
                momentum_15m=tech.momentum_15m,
                vwap_deviation=tech.vwap_deviation,
                sma_crossover=tech.sma_crossover,
                volatility=tech.volatility,
                price=tech.price,
                source=tech.source,
            )
            price_data = PriceDTO(
                price=tech.price,
                change_24h=tech.momentum_15m * 96,
                change_7d=0,
                market_cap=0,
                volume_24h=0,
                last_updated=datetime.utcnow(),
            )
    except Exception:
        pass
    if not price_data:
        try:
            quote = await get_spot_price("BTC")
            if quote:
                price_data = PriceDTO(
                    price=quote.current_price,
                    change_24h=quote.change_24h,
                    change_7d=quote.change_7d,
                    market_cap=quote.market_cap,
                    volume_24h=quote.volume_24h,
                    last_updated=quote.last_updated
                )
        except Exception:
            pass

    # Windows
    windows = []
    try:
        raw_windows = await load_active_windows()
        windows = [
            WindowDTO(
                slug=w.slug,
                market_id=w.market_id,
                up_price=w.up_price,
                down_price=w.down_price,
                window_start=w.window_start,
                window_end=w.window_end,
                volume=w.volume,
                is_active=w.is_active,
                is_upcoming=w.is_upcoming,
                time_until_end=w.time_until_end,
                spread=w.spread,
            )
            for w in raw_windows
        ]
    except Exception:
        pass

    # Signals
    signals = []
    try:
        raw_opps = await evaluate_markets()
        signals = [_opp_to_dto(o, actionable=o.passes_threshold) for o in raw_opps]
    except Exception:
        pass

    # Recent positions
    rows = session.query(Position).order_by(Position.timestamp.desc()).limit(50).all()
    recent = [
        PositionDTO(
            id=r.id,
            market_ticker=r.market_ticker,
            platform=r.platform,
            event_slug=r.event_slug,
            direction=r.direction,
            entry_price=r.entry_price,
            size=r.size,
            timestamp=r.timestamp,
            settled=r.settled,
            result=r.result,
            pnl=r.pnl,
            strategy=r.strategy or 1,
            edge_at_entry=r.edge_at_entry,
        )
        for r in rows
    ]

    # Equity curve
    settled_rows = session.query(Position).filter(Position.settled == True).order_by(Position.timestamp).all()
    curve = []
    cumulative = 0
    for pos in settled_rows:
        if pos.pnl is not None:
            cumulative += pos.pnl
            curve.append({
                "timestamp": pos.timestamp.isoformat(),
                "pnl": cumulative,
                "bankroll": cfg.INITIAL_BANKROLL + cumulative
            })

    # Per-strategy equity curves
    equity_by_strategy = {}
    for strat_id in [1, 2, 3]:
        strat_rows = [r for r in settled_rows if (r.strategy or 1) == strat_id and r.pnl is not None]
        cum = 0
        strat_curve = []
        for pos in strat_rows:
            cum += pos.pnl
            strat_curve.append({
                "timestamp": pos.timestamp.isoformat(),
                "pnl": cum,
                "bankroll": cfg.INITIAL_BANKROLL + cum
            })
        equity_by_strategy[str(strat_id)] = strat_curve

    # Calibration
    cal = _compute_cal_summary(session)

    # Weather data
    wx_signals = []
    wx_forecasts = []
    if cfg.WEATHER_ENABLED:
        try:
            from backend.engine.wx_analysis import evaluate_wx_markets
            from backend.sources.ensemble_forecast import load_ensemble, STATION_REGISTRY

            wx_opps = await evaluate_wx_markets()
            wx_signals = [_wx_opp_to_dto(o) for o in wx_opps]

            city_keys = [c.strip() for c in cfg.WEATHER_CITIES.split(",") if c.strip()]
            for ck in city_keys:
                if ck not in STATION_REGISTRY:
                    continue
                ensemble = await load_ensemble(ck)
                if ensemble:
                    wx_forecasts.append(WxForecastDTO(
                        city_key=ensemble.city_key,
                        city_name=ensemble.city_name,
                        target_date=ensemble.target_date.isoformat(),
                        mean_high=ensemble.mean_high,
                        std_high=ensemble.std_high,
                        mean_low=ensemble.mean_low,
                        std_low=ensemble.std_low,
                        num_members=ensemble.num_members,
                        ensemble_agreement=ensemble.ensemble_agreement,
                    ))
        except Exception:
            pass

    return DashboardDTO(
        stats=stats,
        btc_price=price_data,
        microstructure=tech_data,
        windows=windows,
        active_signals=signals,
        recent_trades=recent,
        equity_curve=curve,
        equity_by_strategy=equity_by_strategy,
        calibration=cal,
        weather_signals=wx_signals,
        weather_forecasts=wx_forecasts,
    )


@app.websocket("/ws/events")
async def websocket_feed(ws: WebSocket):
    await _hub.connect(ws)

    try:
        await ws.send_json({
            "timestamp": datetime.utcnow().isoformat(),
            "type": "success",
            "message": "Connected to BTC trading bot"
        })

        from backend.engine.orchestrator import recent_activities
        for entry in recent_activities(20):
            await ws.send_json(entry)

        prev_count = len(recent_activities(200))
        while True:
            await asyncio.sleep(2)

            current = recent_activities(200)
            if len(current) > prev_count:
                new = current[prev_count - len(current):]
                for entry in new:
                    await ws.send_json(entry)
                prev_count = len(current)

            await ws.send_json({
                "type": "heartbeat",
                "timestamp": datetime.utcnow().isoformat()
            })

    except WebSocketDisconnect:
        _hub.disconnect(ws)
    except Exception:
        _hub.disconnect(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
