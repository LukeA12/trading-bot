"""Automated trading orchestrator — background scheduling and execution."""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func
import logging

from backend.env import cfg
from backend.storage.models import DbSession, Position, PortfolioState, Opportunity
from backend.engine.analysis import evaluate_markets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trading_bot")

_scheduler: Optional[AsyncIOScheduler] = None

_activity_log: List[dict] = []
_MAX_LOG_SIZE = 200


def record_activity(activity_type: str, message: str, data: dict = None):
    """Append an activity entry for real-time display."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "type": activity_type,
        "message": message,
        "data": data or {}
    }
    _activity_log.append(entry)

    while len(_activity_log) > _MAX_LOG_SIZE:
        _activity_log.pop(0)

    log_fn = {
        "error": logger.error,
        "warning": logger.warning,
        "success": logger.info,
        "info": logger.info,
        "data": logger.debug,
        "trade": logger.info
    }.get(activity_type, logger.info)

    log_fn(f"[{activity_type.upper()}] {message}")


def recent_activities(limit: int = 50) -> List[dict]:
    return _activity_log[-limit:]


async def crypto_cycle():
    """
    Periodic job: scan crypto prediction windows, generate signals, open positions.
    """
    record_activity("info", "Scanning BTC 5-min markets...")

    try:
        opps = await evaluate_markets()
        viable = [o for o in opps if o.passes_threshold]

        record_activity("data", f"Found {len(opps)} signals, {len(viable)} actionable", {
            "total_signals": len(opps),
            "actionable": len(viable),
        })

        if not viable:
            record_activity("info", "No actionable BTC signals")
            return

        session = DbSession()
        try:
            portfolio = session.query(PortfolioState).first()
            if not portfolio:
                record_activity("error", "Bot state not initialized")
                return

            if not portfolio.is_running:
                record_activity("info", "Bot is paused, skipping trades")
                return

            MAX_PER_SCAN = 2
            MIN_SIZE = 10
            MAX_FRAC = 0.03
            MAX_PENDING = cfg.MAX_TOTAL_PENDING_TRADES

            # Daily loss circuit breaker
            day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            day_pnl = session.query(func.coalesce(func.sum(Position.pnl), 0.0)).filter(
                Position.settled == True,
                Position.settlement_time >= day_start
            ).scalar()

            if day_pnl <= -cfg.DAILY_LOSS_LIMIT:
                record_activity("warning", f"Daily loss limit hit: ${day_pnl:.2f} (limit: -${cfg.DAILY_LOSS_LIMIT:.0f}). Stopping trades.")
                return

            pending_count = session.query(Position).filter(Position.settled == False).count()
            if pending_count >= MAX_PENDING:
                record_activity("info", f"Max pending trades reached ({pending_count}/{MAX_PENDING})")
                return

            opened = 0
            for opp in viable[:MAX_PER_SCAN]:
                existing = session.query(Position).filter(
                    Position.event_slug == opp.market.slug,
                    Position.settled == False
                ).first()

                if existing:
                    continue

                pos_size = min(opp.suggested_size, portfolio.bankroll * MAX_FRAC)
                pos_size = max(pos_size, MIN_SIZE)

                if portfolio.bankroll < MIN_SIZE:
                    record_activity("warning", f"Bankroll too low: ${portfolio.bankroll:.2f}")
                    break

                if opened >= MAX_PER_SCAN:
                    break

                entry_px = opp.market.up_price if opp.direction == "up" else opp.market.down_price

                pos = Position(
                    market_ticker=opp.market.market_id,
                    platform="polymarket",
                    event_slug=opp.market.slug,
                    direction=opp.direction,
                    entry_price=entry_px,
                    size=pos_size,
                    model_probability=opp.model_probability,
                    market_price_at_entry=opp.market_probability,
                    edge_at_entry=opp.edge
                )

                session.add(pos)
                session.flush()

                linked = session.query(Opportunity).filter(
                    Opportunity.market_ticker == opp.market.market_id,
                    Opportunity.executed == False,
                ).order_by(Opportunity.timestamp.desc()).first()
                if linked:
                    linked.executed = True
                    pos.signal_id = linked.id

                portfolio.total_trades += 1
                opened += 1

                record_activity("trade",
                    f"BTC {opp.direction.upper()} ${pos_size:.0f} @ {entry_px:.0%} | {opp.market.slug}",
                    {
                        "slug": opp.market.slug,
                        "direction": opp.direction,
                        "size": pos_size,
                        "edge": opp.edge,
                        "entry_price": entry_px,
                        "btc_price": opp.btc_price,
                    }
                )

            portfolio.last_run = datetime.utcnow()
            session.commit()

            if opened > 0:
                record_activity("success", f"Executed {opened} BTC trade(s)")
            else:
                record_activity("info", "No new trades executed")

        finally:
            session.close()

    except Exception as exc:
        record_activity("error", f"Scan error: {str(exc)}")
        logger.exception("Error in crypto_cycle")


async def wx_cycle():
    """
    Periodic job: scan weather temperature contracts, open positions for all 3 strategies.
    Strategy 1: Baseline — threshold edge, 1 unit, hold to settlement.
    Strategy 2: Same entry as S1 + early exit logic (managed in wx_exit_cycle).
    Strategy 3: 15%+ edge only, tiered sizing (1/2/5 units), hold to settlement.
    """
    record_activity("info", "Scanning weather temperature markets...")

    try:
        from backend.engine.wx_analysis import evaluate_wx_markets
        from backend.engine.wx_strategies import (
            STRATEGY_1_THRESHOLD, STRATEGY_3_THRESHOLD,
            BASE_UNIT, compute_strategy_3_size, should_take_trade_s3,
        )

        opps = await evaluate_wx_markets()

        def _dedupe_by_city_date(opps_list):
            """Keep only the highest-edge opportunity per (city, date, metric).
            Prevents correlated bets — all range/threshold contracts for the same
            city+date+metric (high or low) depend on the same temperature realization."""
            seen = {}
            for o in sorted(opps_list, key=lambda x: abs(x.edge), reverse=True):
                key = (o.market.city_key, o.market.target_date, o.market.metric)
                if key not in seen:
                    seen[key] = o
            return list(seen.values())

        # Strategy 1 & 2 use the same threshold
        viable_s1 = _dedupe_by_city_date(
            [o for o in opps if abs(o.edge) >= STRATEGY_1_THRESHOLD]
        )
        # Strategy 3 uses 15%+
        viable_s3 = _dedupe_by_city_date(
            [o for o in opps if should_take_trade_s3(o.edge)]
        )

        record_activity("data", f"Weather: {len(opps)} signals, S1/S2={len(viable_s1)}, S3={len(viable_s3)}", {
            "total_signals": len(opps),
            "s1_actionable": len(viable_s1),
            "s3_actionable": len(viable_s3),
        })

        if not viable_s1 and not viable_s3:
            record_activity("info", "No actionable weather signals")
            return

        session = DbSession()
        try:
            portfolio = session.query(PortfolioState).first()
            if not portfolio:
                record_activity("error", "Bot state not initialized")
                return

            if not portfolio.is_running:
                record_activity("info", "Bot is paused, skipping weather trades")
                return

            MAX_PER_STRATEGY = 3

            opened = 0

            # --- Strategy 1 & 2: same entry, 1 unit each ---
            for opp in viable_s1[:MAX_PER_STRATEGY]:
                entry_px = opp.market.yes_price if opp.direction == "yes" else opp.market.no_price

                for strategy_id in [1, 2]:
                    existing = session.query(Position).filter(
                        Position.market_ticker == opp.market.market_id,
                        Position.strategy == strategy_id,
                        Position.settled == False,
                    ).first()
                    if existing:
                        continue

                    pos = Position(
                        market_ticker=opp.market.market_id,
                        platform=opp.market.platform,
                        event_slug=opp.market.slug,
                        market_type="weather",
                        direction=opp.direction,
                        entry_price=entry_px,
                        size=BASE_UNIT,
                        model_probability=opp.model_probability,
                        market_price_at_entry=opp.market_probability,
                        edge_at_entry=opp.edge,
                        strategy=strategy_id,
                    )
                    session.add(pos)
                    session.flush()

                    linked = session.query(Opportunity).filter(
                        Opportunity.market_ticker == opp.market.market_id,
                        Opportunity.market_type == "weather",
                        Opportunity.executed == False,
                    ).order_by(Opportunity.timestamp.desc()).first()
                    if linked:
                        linked.executed = True
                        pos.signal_id = linked.id

                    portfolio.total_trades += 1
                    opened += 1

                    record_activity("trade",
                        f"WX S{strategy_id} {opp.market.city_name}: {opp.direction.upper()} "
                        f"${BASE_UNIT:.0f} @ {entry_px:.0%} | edge {opp.edge:+.1%}",
                        {
                            "strategy": strategy_id,
                            "slug": opp.market.slug,
                            "direction": opp.direction,
                            "size": BASE_UNIT,
                            "edge": opp.edge,
                            "entry_price": entry_px,
                            "city": opp.market.city_name,
                        }
                    )

            # --- Strategy 3: 15%+ edge, tiered sizing ---
            for opp in viable_s3[:MAX_PER_STRATEGY]:
                existing = session.query(Position).filter(
                    Position.market_ticker == opp.market.market_id,
                    Position.strategy == 3,
                    Position.settled == False,
                ).first()
                if existing:
                    continue

                entry_px = opp.market.yes_price if opp.direction == "yes" else opp.market.no_price
                pos_size = compute_strategy_3_size(opp.edge)

                pos = Position(
                    market_ticker=opp.market.market_id,
                    platform=opp.market.platform,
                    event_slug=opp.market.slug,
                    market_type="weather",
                    direction=opp.direction,
                    entry_price=entry_px,
                    size=pos_size,
                    model_probability=opp.model_probability,
                    market_price_at_entry=opp.market_probability,
                    edge_at_entry=opp.edge,
                    strategy=3,
                )
                session.add(pos)
                session.flush()

                linked = session.query(Opportunity).filter(
                    Opportunity.market_ticker == opp.market.market_id,
                    Opportunity.market_type == "weather",
                    Opportunity.executed == False,
                ).order_by(Opportunity.timestamp.desc()).first()
                if linked:
                    linked.executed = True
                    pos.signal_id = linked.id

                portfolio.total_trades += 1
                opened += 1

                units = pos_size / BASE_UNIT
                record_activity("trade",
                    f"WX S3 {opp.market.city_name}: {opp.direction.upper()} "
                    f"${pos_size:.0f} ({units:.0f}u) @ {entry_px:.0%} | edge {opp.edge:+.1%}",
                    {
                        "strategy": 3,
                        "slug": opp.market.slug,
                        "direction": opp.direction,
                        "size": pos_size,
                        "edge": opp.edge,
                        "entry_price": entry_px,
                        "city": opp.market.city_name,
                    }
                )

            portfolio.last_run = datetime.utcnow()
            session.commit()

            if opened > 0:
                record_activity("success", f"Executed {opened} weather trade(s) across strategies")
            else:
                record_activity("info", "No new weather trades executed")

        finally:
            session.close()

    except Exception as exc:
        record_activity("error", f"Weather scan error: {str(exc)}")
        logger.exception("Error in wx_cycle")


async def wx_exit_cycle():
    """
    Strategy 2 early exit logic — runs periodically to check if S2 positions
    should be closed before settlement based on current market price.
    """
    try:
        from backend.engine.wx_strategies import (
            EARLY_EXIT_ENTRY_THRESHOLD,
            EARLY_EXIT_MIN_HOURS_REMAINING,
            EARLY_EXIT_HOLD_ENTRY,
            EARLY_EXIT_HOLD_AGREEMENT,
            NO_EXIT_HOURS_REMAINING,
        )
        import httpx
        from datetime import date

        session = DbSession()
        try:
            s2_positions = session.query(Position).filter(
                Position.strategy == 2,
                Position.settled == False,
                Position.market_type == "weather",
            ).all()

            if not s2_positions:
                return

            for pos in s2_positions:
                # Rule: Entry >= 50¢ → hold to settlement
                if pos.entry_price >= EARLY_EXIT_HOLD_ENTRY:
                    continue

                # Rule: Entry < 45¢ → consider early exit
                if pos.entry_price >= EARLY_EXIT_ENTRY_THRESHOLD:
                    continue

                # Estimate hours remaining (weather contracts settle same day ~midnight UTC)
                now = datetime.utcnow()
                # Assume settlement at end of target date (approx 23:59 UTC)
                settle_hour = now.replace(hour=23, minute=59, second=0)
                hours_left = (settle_hour - now).total_seconds() / 3600

                # Rule: Never exit within 2 hours of settlement
                if hours_left < NO_EXIT_HOURS_REMAINING:
                    continue

                # Rule: Only exit if 4+ hours remain
                if hours_left < EARLY_EXIT_MIN_HOURS_REMAINING:
                    continue

                # Check current market price
                try:
                    async with httpx.AsyncClient(timeout=10.0) as http:
                        resp = await http.get(
                            f"https://gamma-api.polymarket.com/markets/{pos.market_ticker}"
                        )
                        if resp.status_code != 200:
                            continue
                        mkt = resp.json()
                        prices = mkt.get("outcomePrices", [])
                        if isinstance(prices, str):
                            import json
                            prices = json.loads(prices)
                        if not prices or len(prices) < 2:
                            continue

                        current_yes = float(prices[0])
                        current_no = float(prices[1])
                        current_px = current_yes if pos.direction == "yes" else current_no
                except Exception:
                    continue

                # Exit if current price has reached our model's fair value (edge closed)
                model_fair = pos.model_probability if pos.direction == "yes" else (1 - pos.model_probability)
                if current_px >= model_fair:
                    # Simulate early exit: PnL = (current_price - entry_price) * contracts
                    pnl = (current_px - pos.entry_price) * pos.size
                    pos.settled = True
                    pos.settlement_time = now
                    pos.settlement_value = current_px
                    pos.result = "win" if pnl > 0 else "loss"
                    pos.pnl = pnl

                    record_activity("trade",
                        f"WX S2 EARLY EXIT: {pos.event_slug} | "
                        f"entry={pos.entry_price:.0%} → exit={current_px:.0%} | PnL ${pnl:.2f}",
                        {"strategy": 2, "pnl": pnl, "exit_type": "early"}
                    )

            session.commit()
        finally:
            session.close()

    except Exception as exc:
        record_activity("error", f"S2 exit check error: {str(exc)}")
        logger.exception("Error in wx_exit_cycle")


async def resolution_cycle():
    """
    Periodic job: settle pending positions against real market outcomes.
    """
    record_activity("info", "Checking BTC trade settlements...")

    try:
        from backend.engine.resolution import process_open_positions, sync_portfolio

        session = DbSession()
        try:
            pending = session.query(Position).filter(Position.settled == False).count()

            if pending == 0:
                record_activity("data", "No pending trades to settle")
                return

            record_activity("data", f"Processing {pending} pending trades")

            resolved = await process_open_positions(session)

            if resolved:
                await sync_portfolio(session, resolved)

                wins = sum(1 for p in resolved if p.result == "win")
                losses = sum(1 for p in resolved if p.result == "loss")
                total_pnl = sum(p.pnl for p in resolved if p.pnl is not None)

                record_activity("success", f"Settled {len(resolved)} trades: {wins}W/{losses}L, P&L: ${total_pnl:.2f}", {
                    "settled_count": len(resolved),
                    "wins": wins,
                    "losses": losses,
                    "pnl": total_pnl
                })

                for pos in resolved:
                    prefix = "+" if pos.pnl and pos.pnl > 0 else ""
                    record_activity("data", f"  {pos.event_slug}: {pos.result.upper()} {prefix}${pos.pnl:.2f}")
            else:
                record_activity("info", "No trades ready for settlement")

        finally:
            session.close()

    except Exception as exc:
        record_activity("error", f"Settlement error: {str(exc)}")
        logger.exception("Error in resolution_cycle")


async def pulse_check():
    """Periodic health check."""
    session = None
    try:
        session = DbSession()
        portfolio = session.query(PortfolioState).first()
        pending = session.query(Position).filter(Position.settled == False).count()

        if portfolio is None:
            record_activity("warning", "Heartbeat: Bot state not initialized")
            return

        record_activity("data", f"Heartbeat: {pending} pending trades, bankroll: ${portfolio.bankroll:.2f}", {
            "pending_trades": pending,
            "bankroll": portfolio.bankroll,
            "is_running": portfolio.is_running
        })
    except Exception as exc:
        record_activity("warning", f"Heartbeat failed: {str(exc)}")
    finally:
        if session:
            session.close()


def launch_automation():
    """Start background scheduling for all automated cycles."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        record_activity("warning", "Scheduler already running")
        return

    _scheduler = AsyncIOScheduler()

    scan_sec = cfg.SCAN_INTERVAL_SECONDS
    settle_sec = cfg.SETTLEMENT_INTERVAL_SECONDS

    if cfg.BTC_ENABLED:
        _scheduler.add_job(
            crypto_cycle,
            IntervalTrigger(seconds=scan_sec),
            id="market_scan",
            replace_existing=True,
            max_instances=1
        )

    _scheduler.add_job(
        resolution_cycle,
        IntervalTrigger(seconds=settle_sec),
        id="settlement_check",
        replace_existing=True,
        max_instances=1
    )

    _scheduler.add_job(
        pulse_check,
        IntervalTrigger(minutes=1),
        id="heartbeat",
        replace_existing=True,
        max_instances=1
    )

    if cfg.WEATHER_ENABLED:
        wx_scan_sec = cfg.WEATHER_SCAN_INTERVAL_SECONDS

        _scheduler.add_job(
            wx_cycle,
            IntervalTrigger(seconds=wx_scan_sec),
            id="weather_scan",
            replace_existing=True,
            max_instances=1,
        )

        _scheduler.add_job(
            wx_exit_cycle,
            IntervalTrigger(minutes=10),
            id="weather_s2_exit",
            replace_existing=True,
            max_instances=1,
        )

    _scheduler.start()
    record_activity("success", "BTC 5-min trading scheduler started", {
        "scan_interval": f"{scan_sec}s",
        "settlement_interval": f"{settle_sec}s",
        "min_edge": f"{cfg.MIN_EDGE_THRESHOLD:.0%}",
        "weather_enabled": cfg.WEATHER_ENABLED,
    })

    if cfg.BTC_ENABLED:
        asyncio.create_task(crypto_cycle())

    if cfg.WEATHER_ENABLED:
        asyncio.create_task(wx_cycle())


def halt_automation():
    """Stop all background scheduling."""
    global _scheduler

    if _scheduler is None or not _scheduler.running:
        record_activity("info", "Scheduler not running")
        return

    _scheduler.shutdown(wait=False)
    _scheduler = None
    record_activity("info", "Scheduler stopped")


def automation_active() -> bool:
    return _scheduler is not None and _scheduler.running


async def trigger_scan():
    if not cfg.BTC_ENABLED:
        record_activity("info", "BTC trading is disabled (BTC_ENABLED=false)")
        return
    record_activity("info", "Manual scan triggered")
    await crypto_cycle()


async def trigger_resolution():
    record_activity("info", "Manual settlement triggered")
    await resolution_cycle()
