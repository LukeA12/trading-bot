"""Position resolution engine — settles open positions against real market outcomes."""
import httpx
import json
import logging
from datetime import datetime, date
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session

from backend.storage.models import Position, PortfolioState, Opportunity

logger = logging.getLogger("trading_bot")


async def check_polymarket_outcome(market_id: str, event_slug: Optional[str] = None) -> Tuple[bool, Optional[float]]:
    """
    Query Polymarket for a market's resolution status.

    Returns: (is_resolved, settlement_value)
        - settlement_value: 1.0 if Up/Yes won, 0.0 if Down/No won
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            if event_slug:
                resp = await http.get(
                    "https://gamma-api.polymarket.com/events",
                    params={"slug": event_slug}
                )
                resp.raise_for_status()
                events = resp.json()

                if events:
                    event = events[0] if isinstance(events, list) else events
                    mkt_list = event.get("markets", [])
                    if mkt_list:
                        return _interpret_outcome(mkt_list[0])

            url = f"https://gamma-api.polymarket.com/markets/{market_id}"
            resp = await http.get(url)

            if resp.status_code == 404:
                return await _search_events_for_market(market_id)

            resp.raise_for_status()
            mkt = resp.json()
            return _interpret_outcome(mkt)

    except Exception as exc:
        logger.warning(f"Failed to fetch resolution for {event_slug or market_id}: {exc}")
        return False, None


async def _search_events_for_market(market_id: str) -> Tuple[bool, Optional[float]]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            for closed in [True, False]:
                params = {
                    "closed": str(closed).lower(),
                    "limit": 200
                }
                resp = await http.get(
                    "https://gamma-api.polymarket.com/events",
                    params=params
                )
                resp.raise_for_status()
                events = resp.json()

                for event in events:
                    for mkt in event.get("markets", []):
                        if str(mkt.get("id")) == str(market_id):
                            return _interpret_outcome(mkt)

        return False, None

    except Exception as exc:
        logger.warning(f"Failed to search for market {market_id}: {exc}")
        return False, None


def _interpret_outcome(mkt: dict) -> Tuple[bool, Optional[float]]:
    """
    Parse market data to determine resolution status.
    outcomePrices[0] > 0.99 → first outcome won (Yes/Up)
    outcomePrices[0] < 0.01 → second outcome won (No/Down)
    """
    if not mkt.get("closed", False):
        return False, None

    prices = mkt.get("outcomePrices", [])
    if not prices:
        return False, None

    try:
        if isinstance(prices, str):
            prices = json.loads(prices)

        first = float(prices[0]) if prices else 0.5

        if first > 0.99:
            logger.info(f"Market {mkt.get('id')} resolved: UP/YES won")
            return True, 1.0
        elif first < 0.01:
            logger.info(f"Market {mkt.get('id')} resolved: DOWN/NO won")
            return True, 0.0
        else:
            return False, None

    except (ValueError, IndexError, TypeError) as exc:
        logger.warning(f"Failed to parse outcome prices: {exc}")
        return False, None


def compute_return(pos: Position, settlement_val: float) -> float:
    """
    Calculate P&L for a position given the settlement outcome.

    Maps up→yes, down→no internally.
    """
    dir_mapped = pos.direction
    if dir_mapped == "up":
        dir_mapped = "yes"
    elif dir_mapped == "down":
        dir_mapped = "no"

    if dir_mapped == "yes":
        if settlement_val == 1.0:
            pnl = pos.size * (1.0 - pos.entry_price)
        else:
            pnl = -pos.size * pos.entry_price
    else:
        if settlement_val == 0.0:
            pnl = pos.size * (1.0 - pos.entry_price)
        else:
            pnl = -pos.size * pos.entry_price

    return round(pnl, 2)


async def evaluate_position_outcome(pos: Position) -> Tuple[bool, Optional[float], Optional[float]]:
    """Check if a position's underlying market has settled."""
    is_resolved, settlement_val = await check_polymarket_outcome(
        pos.market_ticker,
        event_slug=pos.event_slug
    )

    if not is_resolved or settlement_val is None:
        return False, None, None

    pnl = compute_return(pos, settlement_val)

    mapped = "UP" if pos.direction in ("up", "yes") else "DOWN"
    outcome = "UP" if settlement_val == 1.0 else "DOWN"
    result = "WIN" if mapped == outcome else "LOSS"

    logger.info(f"Position {pos.id} settled: {mapped} @ {pos.entry_price:.0%} -> "
                f"{result} P&L: ${pnl:+.2f}")

    return True, settlement_val, pnl


async def evaluate_wx_position(pos: Position) -> Tuple[bool, Optional[float], Optional[float]]:
    """Check settlement for a weather position, routing by platform."""
    platform = getattr(pos, 'platform', 'polymarket') or 'polymarket'

    if platform == "kalshi":
        is_resolved, settlement_val = await _check_kalshi_outcome(pos.market_ticker)
    else:
        is_resolved, settlement_val = await check_polymarket_outcome(
            pos.market_ticker,
            event_slug=pos.event_slug,
        )

    if is_resolved and settlement_val is not None:
        pnl = compute_return(pos, settlement_val)
        return True, settlement_val, pnl

    return False, None, None


async def _check_kalshi_outcome(ticker: str) -> Tuple[bool, Optional[float]]:
    try:
        from backend.sources.kalshi_api import KalshiConnector, kalshi_configured

        if not kalshi_configured():
            return False, None

        connector = KalshiConnector()
        data = await connector.get_market(ticker)
        mkt = data.get("market", data)

        status = mkt.get("status", "")
        result = mkt.get("result", "")

        if status in ("finalized", "determined") and result:
            if result == "yes":
                return True, 1.0
            elif result == "no":
                return True, 0.0

        return False, None

    except Exception as exc:
        logger.warning(f"Failed to fetch Kalshi resolution for {ticker}: {exc}")
        return False, None


async def process_open_positions(session: Session) -> List[Position]:
    """Process all unsettled positions for resolution."""
    try:
        pending = session.query(Position).filter(Position.settled == False).all()
    except Exception as exc:
        logger.error(f"Failed to query pending positions: {exc}")
        return []

    if not pending:
        logger.info("No pending positions to settle")
        return []

    logger.info(f"Checking {len(pending)} pending positions for settlement...")
    resolved = []

    for pos in pending:
        try:
            mkt_type = getattr(pos, 'market_type', 'btc') or 'btc'
            if mkt_type == "weather":
                settled, settlement_val, pnl = await evaluate_wx_position(pos)
            else:
                settled, settlement_val, pnl = await evaluate_position_outcome(pos)

            if settled and settlement_val is not None:
                pos.settled = True
                pos.settlement_value = settlement_val
                pos.pnl = pnl
                pos.settlement_time = datetime.utcnow()

                if pnl is not None and pnl > 0:
                    pos.result = "win"
                elif pnl is not None and pnl < 0:
                    pos.result = "loss"
                else:
                    pos.result = "push"

                resolved.append(pos)

                # Update linked Opportunity with actual outcome
                if pos.signal_id:
                    linked = session.query(Opportunity).filter(Opportunity.id == pos.signal_id).first()
                    if linked:
                        actual = "up" if settlement_val == 1.0 else "down"
                        linked.actual_outcome = actual
                        linked.outcome_correct = (linked.direction == actual)
                        linked.settlement_value = settlement_val
                        linked.settled_at = datetime.utcnow()
        except Exception as exc:
            logger.error(f"Failed to settle position {pos.id}: {exc}")
            continue

    if resolved:
        try:
            session.commit()
            logger.info(f"Settled {len(resolved)} positions")
        except Exception as exc:
            logger.error(f"Failed to commit settlements: {exc}")
            session.rollback()
            return []
    else:
        logger.info("No positions ready for settlement (markets still open)")

    return resolved


async def sync_portfolio(session: Session, resolved: List[Position]) -> None:
    """Update portfolio state with P&L from resolved positions."""
    if not resolved:
        return

    try:
        portfolio = session.query(PortfolioState).first()
        if not portfolio:
            logger.warning("Portfolio state not found")
            return

        for pos in resolved:
            if pos.pnl is not None:
                portfolio.total_pnl += pos.pnl
                portfolio.bankroll += pos.pnl
                if pos.result == "win":
                    portfolio.winning_trades += 1

        session.commit()
        logger.info(f"Updated portfolio: Bankroll ${portfolio.bankroll:.2f}, P&L ${portfolio.total_pnl:+.2f}")
    except Exception as exc:
        logger.error(f"Failed to update portfolio state: {exc}")
        session.rollback()
