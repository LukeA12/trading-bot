"""Market analysis engine for crypto 5-minute prediction windows."""
import logging
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, field
import asyncio

from backend.env import cfg
from backend.sources.polymarket_btc import CryptoWindow, load_active_windows
from backend.sources.price_feed import get_spot_price, snapshot_technicals
from backend.storage.models import DbSession, Opportunity

logger = logging.getLogger("trading_bot")


@dataclass
class MarketOpportunity:
    """Identified trading opportunity in a crypto prediction window."""
    market: CryptoWindow

    model_probability: float = 0.5
    market_probability: float = 0.5
    edge: float = 0.0
    direction: str = "up"

    confidence: float = 0.5
    kelly_fraction: float = 0.0
    suggested_size: float = 0.0

    sources: List[str] = field(default_factory=list)
    reasoning: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    btc_price: float = 0.0
    btc_change_1h: float = 0.0
    btc_change_24h: float = 0.0

    @property
    def passes_threshold(self) -> bool:
        return abs(self.edge) >= cfg.MIN_EDGE_THRESHOLD


def compute_advantage(
    model_prob: float,
    market_price: float
) -> tuple[float, str]:
    """
    Determine edge magnitude and optimal direction.

    Returns (edge, direction) where direction is "up" or "down".
    """
    up_adv = model_prob - market_price
    down_adv = (1 - model_prob) - (1 - market_price)

    if up_adv >= down_adv:
        return up_adv, "up"
    else:
        return down_adv, "down"


def optimal_stake(
    edge: float,
    probability: float,
    market_price: float,
    direction: str,
    bankroll: float
) -> float:
    """
    Fractional Kelly criterion position sizing.

    f = (p * b - q) / b
    """
    if direction == "up":
        win_p = probability
        px = market_price
    else:
        win_p = 1 - probability
        px = 1 - market_price

    if px <= 0 or px >= 1:
        return 0

    odds = (1 - px) / px

    lose_p = 1 - win_p
    kelly = (win_p * odds - lose_p) / odds

    kelly *= cfg.KELLY_FRACTION

    cap = 0.05
    kelly = min(kelly, cap)
    kelly = max(kelly, 0)

    stake = kelly * bankroll
    stake = min(stake, cfg.MAX_TRADE_SIZE)

    return stake


async def assess_window(window: CryptoWindow) -> Optional[MarketOpportunity]:
    """
    Evaluate a single crypto prediction window using real-time technical indicators.

    Composite signal from RSI, momentum, VWAP deviation, SMA crossover, and market skew.
    Convergence filter requires 2/4 indicators to agree.
    """
    try:
        tech = await snapshot_technicals()
    except Exception as exc:
        logger.warning(f"Failed to compute technicals: {exc}")
        return None

    if not tech:
        return None

    mkt_up_prob = window.up_price

    if mkt_up_prob < 0.02 or mkt_up_prob > 0.98:
        return None

    # RSI mean-reversion signal
    if tech.rsi < 30:
        rsi_sig = 0.5 + (30 - tech.rsi) / 30
    elif tech.rsi > 70:
        rsi_sig = -0.5 - (tech.rsi - 70) / 30
    elif tech.rsi < 45:
        rsi_sig = (45 - tech.rsi) / 30
    elif tech.rsi > 55:
        rsi_sig = -(tech.rsi - 55) / 30
    else:
        rsi_sig = 0.0
    rsi_sig = max(-1.0, min(1.0, rsi_sig))

    # Weighted momentum blend
    mom_blend = tech.momentum_1m * 0.5 + tech.momentum_5m * 0.35 + tech.momentum_15m * 0.15
    mom_sig = max(-1.0, min(1.0, mom_blend / 0.10))

    # VWAP deviation
    vwap_sig = max(-1.0, min(1.0, tech.vwap_deviation / 0.05))

    # SMA crossover
    sma_sig = max(-1.0, min(1.0, tech.sma_crossover / 0.03))

    # Contrarian market skew
    skew = mkt_up_prob - 0.50
    skew_sig = max(-1.0, min(1.0, -skew * 4))

    # Convergence check
    indicators = [rsi_sig, mom_sig, vwap_sig, sma_sig]
    up_count = sum(1 for s in indicators if s > 0.05)
    down_count = sum(1 for s in indicators if s < -0.05)

    converged = up_count >= 2 or down_count >= 2

    # Weighted composite
    w = cfg
    composite = (
        rsi_sig * w.WEIGHT_RSI
        + mom_sig * w.WEIGHT_MOMENTUM
        + vwap_sig * w.WEIGHT_VWAP
        + sma_sig * w.WEIGHT_SMA
        + skew_sig * w.WEIGHT_MARKET_SKEW
    )

    model_up = 0.50 + composite * 0.15
    model_up = max(0.35, min(0.65, model_up))

    adv, direction = compute_advantage(model_up, mkt_up_prob)

    entry_px = mkt_up_prob if direction == "up" else window.down_price

    # Time filter
    now = datetime.utcnow()
    win_end = window.window_end
    if win_end.tzinfo is not None:
        win_end = win_end.replace(tzinfo=None)
    remaining = (win_end - now).total_seconds()
    time_ok = cfg.MIN_TIME_REMAINING <= remaining <= cfg.MAX_TIME_REMAINING

    filters_pass = converged and entry_px <= cfg.MAX_ENTRY_PRICE and time_ok

    if not filters_pass:
        adv = 0.0

    # Confidence metric
    vol_factor = min(1.0, tech.volatility / 0.05) if tech.volatility > 0 else 0.5
    convergence_str = max(up_count, down_count) / 4.0
    conf = min(0.8, 0.3 + convergence_str * 0.3 + abs(composite) * 0.2) * vol_factor

    # Position sizing
    capital = cfg.INITIAL_BANKROLL
    stake = optimal_stake(
        edge=abs(adv),
        probability=model_up,
        market_price=mkt_up_prob,
        direction=direction,
        bankroll=capital,
    )

    # Reasoning string
    status = "ACTIONABLE" if filters_pass else "FILTERED"
    filter_notes = []
    if not converged:
        filter_notes.append(f"convergence {max(up_count, down_count)}/4 < 2")
    if not time_ok:
        filter_notes.append(f"time {remaining:.0f}s not in [{cfg.MIN_TIME_REMAINING},{cfg.MAX_TIME_REMAINING}]")
    if entry_px > cfg.MAX_ENTRY_PRICE:
        filter_notes.append(f"entry {entry_px:.0%} > {cfg.MAX_ENTRY_PRICE:.0%}")
    note = f" [{', '.join(filter_notes)}]" if filter_notes else ""

    reasoning = (
        f"[{status}]{note} "
        f"BTC ${tech.price:,.0f} | RSI:{tech.rsi:.0f} Mom1m:{tech.momentum_1m:+.3f}% "
        f"Mom5m:{tech.momentum_5m:+.3f}% VWAP:{tech.vwap_deviation:+.3f}% "
        f"SMA:{tech.sma_crossover:+.4f}% Vol:{tech.volatility:.4f}% | "
        f"Composite:{composite:+.3f} -> Model UP:{model_up:.0%} vs Mkt:{mkt_up_prob:.0%} | "
        f"Edge:{adv:+.1%} -> {direction.upper()} @ {entry_px:.0%} | "
        f"Convergence:{max(up_count, down_count)}/4 | "
        f"Window ends: {window.window_end.strftime('%H:%M UTC')}"
    )

    return MarketOpportunity(
        market=window,
        model_probability=model_up,
        market_probability=mkt_up_prob,
        edge=adv,
        direction=direction,
        confidence=conf,
        kelly_fraction=stake / capital if capital > 0 else 0,
        suggested_size=stake,
        sources=[f"binance_microstructure_{tech.source}"],
        reasoning=reasoning,
        btc_price=tech.price,
        btc_change_1h=tech.momentum_5m * 12,
        btc_change_24h=tech.momentum_15m * 96,
    )


async def evaluate_markets() -> List[MarketOpportunity]:
    """Scan all active crypto prediction windows and generate opportunities."""
    opportunities = []

    logger.info("=" * 50)
    logger.info("BTC 5-MIN SCAN: Fetching markets from Polymarket...")

    try:
        windows = await load_active_windows()
    except Exception as exc:
        logger.error(f"Failed to fetch crypto windows: {exc}")
        windows = []

    logger.info(f"Found {len(windows)} active BTC 5-min markets")

    for window in windows:
        try:
            opp = await assess_window(window)
            if opp:
                opportunities.append(opp)
        except Exception as exc:
            logger.debug(f"Assessment failed for {window.slug}: {exc}")

        await asyncio.sleep(0.1)

    opportunities.sort(key=lambda o: abs(o.edge), reverse=True)

    viable = [o for o in opportunities if o.passes_threshold]
    logger.info(f"=" * 50)
    logger.info(f"SCAN COMPLETE: {len(opportunities)} signals, {len(viable)} actionable")

    for opp in viable[:5]:
        logger.info(f"  {opp.market.slug}")
        logger.info(f"    Edge: {opp.edge:+.1%} -> {opp.direction.upper()} @ ${opp.suggested_size:.2f}")

    _store_opportunities(opportunities)

    return opportunities


def _store_opportunities(opps: list):
    """Persist non-zero-edge opportunities to DB for calibration tracking."""
    to_save = [o for o in opps if abs(o.edge) > 0]
    if not to_save:
        return

    session = DbSession()
    try:
        for opp in to_save:
            existing = session.query(Opportunity).filter(
                Opportunity.market_ticker == opp.market.market_id,
                Opportunity.timestamp >= opp.timestamp.replace(second=0, microsecond=0),
            ).first()
            if existing:
                continue

            row = Opportunity(
                market_ticker=opp.market.market_id,
                platform="polymarket",
                timestamp=opp.timestamp,
                direction=opp.direction,
                model_probability=opp.model_probability,
                market_price=opp.market_probability,
                edge=opp.edge,
                confidence=opp.confidence,
                kelly_fraction=opp.kelly_fraction,
                suggested_size=opp.suggested_size,
                sources=opp.sources,
                reasoning=opp.reasoning,
                executed=False,
            )
            session.add(row)

        session.commit()
    except Exception as exc:
        logger.warning(f"Failed to persist opportunities: {exc}")
        session.rollback()
    finally:
        session.close()


async def get_viable_opportunities() -> List[MarketOpportunity]:
    all_opps = await evaluate_markets()
    return [o for o in all_opps if o.passes_threshold]


if __name__ == "__main__":
    async def test():
        print("Scanning crypto prediction windows...")
        opps = await evaluate_markets()
        print(f"\nFound {len(opps)} total opportunities")

        viable = [o for o in opps if o.passes_threshold]
        print(f"Viable (>{cfg.MIN_EDGE_THRESHOLD:.0%} edge): {len(viable)}")

        for opp in viable[:5]:
            print(f"\n{opp.market.slug}")
            print(f"  BTC: ${opp.btc_price:,.0f} ({opp.btc_change_24h:+.2f}%)")
            print(f"  Model UP: {opp.model_probability:.1%} vs Market UP: {opp.market_probability:.1%}")
            print(f"  Edge: {opp.edge:+.1%} -> {opp.direction.upper()}")
            print(f"  Size: ${opp.suggested_size:.2f}")

    asyncio.run(test())
