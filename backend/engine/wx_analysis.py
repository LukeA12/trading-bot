"""Weather market analysis engine using ensemble forecast data."""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from backend.env import cfg
from backend.engine.analysis import compute_advantage, optimal_stake
from backend.sources.ensemble_forecast import load_ensemble, WeatherEnsemble, STATION_REGISTRY
from backend.sources.polymarket_weather import TempContract, load_poly_temp_contracts
from backend.storage.models import DbSession, Opportunity

logger = logging.getLogger("trading_bot")


@dataclass
class WxOpportunity:
    """Identified opportunity in a weather temperature contract."""
    market: TempContract

    model_probability: float = 0.5
    market_probability: float = 0.5
    edge: float = 0.0
    direction: str = "yes"

    confidence: float = 0.5
    kelly_fraction: float = 0.0
    suggested_size: float = 0.0

    sources: List[str] = field(default_factory=list)
    reasoning: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    ensemble_mean: float = 0.0
    ensemble_std: float = 0.0
    ensemble_members: int = 0

    @property
    def passes_threshold(self) -> bool:
        return abs(self.edge) >= cfg.WEATHER_MIN_EDGE_THRESHOLD


async def assess_wx_market(contract: TempContract) -> Optional[WxOpportunity]:
    """
    Evaluate a temperature contract against ensemble forecast data.
    Computes model probability from member count above/below threshold.
    """
    ensemble = await load_ensemble(contract.city_key, contract.target_date)
    if not ensemble or not ensemble.member_highs:
        return None

    # Compute model probability for YES outcome
    members = ensemble.member_highs if contract.metric == "high" else ensemble.member_lows

    if contract.is_range_contract:
        # Range contract: "between X-Y°F" — compute P(low <= temp <= high)
        lo = contract.range_low_f
        hi = contract.range_high_f
        in_band = sum(1 for m in members if lo <= m <= hi)
        model_yes = in_band / len(members) if members else 0.5
    elif contract.metric == "high":
        if contract.direction == "above":
            model_yes = ensemble.probability_high_above(contract.threshold_f)
        else:
            model_yes = ensemble.probability_high_below(contract.threshold_f)
    else:
        if contract.direction == "above":
            model_yes = ensemble.probability_low_above(contract.threshold_f)
        else:
            model_yes = ensemble.probability_low_below(contract.threshold_f)

    model_yes = max(0.05, min(0.95, model_yes))

    mkt_yes = contract.yes_price

    adv, dir_raw = compute_advantage(model_yes, mkt_yes)
    direction = "yes" if dir_raw == "up" else "no"

    # Entry price filter: skip if entry is above max OR below min
    entry_px = contract.yes_price if direction == "yes" else contract.no_price
    if entry_px > cfg.WEATHER_MAX_ENTRY_PRICE or entry_px < 0.08:
        adv = 0.0

    # Confidence from ensemble agreement
    if contract.is_range_contract:
        lo = contract.range_low_f
        hi = contract.range_high_f
        in_band = sum(1 for m in members if lo <= m <= hi)
        agreement = in_band / len(members) if members else 0.5
    else:
        above = sum(1 for m in members if m > contract.threshold_f)
        agreement = max(above, len(members) - above) / len(members)
    conf = min(0.9, agreement)

    # Position sizing
    capital = cfg.INITIAL_BANKROLL
    stake = optimal_stake(
        edge=abs(adv),
        probability=model_yes,
        market_price=mkt_yes,
        direction=dir_raw,
        bankroll=capital,
    )
    stake = min(stake, cfg.WEATHER_MAX_TRADE_SIZE)

    # Display values
    mean_val = ensemble.mean_high if contract.metric == "high" else ensemble.mean_low
    std_val = ensemble.std_high if contract.metric == "high" else ensemble.std_low

    # Build reasoning
    status = "ACTIONABLE" if abs(adv) >= cfg.WEATHER_MIN_EDGE_THRESHOLD else "FILTERED"
    filter_notes = []
    if entry_px > cfg.WEATHER_MAX_ENTRY_PRICE:
        filter_notes.append(f"entry {entry_px:.0%} > {cfg.WEATHER_MAX_ENTRY_PRICE:.0%}")
    note = f" [{', '.join(filter_notes)}]" if filter_notes else ""

    reasoning = (
        f"[{status}]{note} "
        f"{contract.city_name} {contract.metric} {contract.direction} {contract.threshold_f:.0f}F on {contract.target_date} | "
        f"Ensemble: {mean_val:.1f}F +/- {std_val:.1f}F ({ensemble.num_members} members) | "
        f"Model YES: {model_yes:.0%} vs Market: {mkt_yes:.0%} | "
        f"Edge: {adv:+.1%} -> {direction.upper()} @ {entry_px:.0%} | "
        f"Agreement: {agreement:.0%}"
    )

    return WxOpportunity(
        market=contract,
        model_probability=model_yes,
        market_probability=mkt_yes,
        edge=adv,
        direction=direction,
        confidence=conf,
        kelly_fraction=stake / capital if capital > 0 else 0,
        suggested_size=stake,
        sources=[f"open_meteo_ensemble_{ensemble.num_members}m"],
        reasoning=reasoning,
        ensemble_mean=mean_val,
        ensemble_std=std_val,
        ensemble_members=ensemble.num_members,
    )


async def evaluate_wx_markets() -> List[WxOpportunity]:
    """Scan all active weather temperature contracts and generate opportunities."""
    opps = []

    city_keys = [c.strip() for c in cfg.WEATHER_CITIES.split(",") if c.strip()]

    logger.info("=" * 50)
    logger.info("WEATHER SCAN: Fetching temperature markets...")

    contracts = []

    # Polymarket
    try:
        poly = await load_poly_temp_contracts(city_keys)
        contracts.extend(poly)
        logger.info(f"Polymarket: {len(poly)} weather markets")
    except Exception as exc:
        logger.error(f"Failed to fetch Polymarket weather markets: {exc}")

    # Kalshi
    if cfg.KALSHI_ENABLED:
        try:
            from backend.sources.kalshi_api import kalshi_configured
            from backend.sources.kalshi_weather import load_kalshi_temp_contracts
            if kalshi_configured():
                kalshi = await load_kalshi_temp_contracts(city_keys)
                contracts.extend(kalshi)
                logger.info(f"Kalshi: {len(kalshi)} weather markets")
        except Exception as exc:
            logger.error(f"Failed to fetch Kalshi weather markets: {exc}")

    logger.info(f"Found {len(contracts)} total weather temperature markets")

    for contract in contracts:
        try:
            opp = await assess_wx_market(contract)
            if opp:
                opps.append(opp)
        except Exception as exc:
            logger.debug(f"Weather assessment failed for {contract.title}: {exc}")

    opps.sort(key=lambda o: abs(o.edge), reverse=True)

    viable = [o for o in opps if o.passes_threshold]
    logger.info(f"WEATHER SCAN COMPLETE: {len(opps)} signals, {len(viable)} actionable")

    for opp in viable[:5]:
        logger.info(f"  {opp.market.city_name}: {opp.market.metric} {opp.market.direction} "
                     f"{opp.market.threshold_f:.0f}F | Edge: {opp.edge:+.1%}")

    _store_wx_opportunities(opps)

    return opps


def _store_wx_opportunities(opps: list):
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
                platform=opp.market.platform,
                market_type="weather",
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
        logger.warning(f"Failed to persist weather opportunities: {exc}")
        session.rollback()
    finally:
        session.close()
