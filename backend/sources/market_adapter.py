"""Normalized market adapter — converts platform-specific data to a common schema."""
import logging
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass

from backend.sources.polymarket_btc import CryptoWindow, load_active_windows

logger = logging.getLogger(__name__)


@dataclass
class NormalizedMarket:
    """Platform-agnostic market representation."""
    platform: str
    ticker: str
    title: str
    category: str
    subcategory: Optional[str]

    yes_price: float
    no_price: float
    volume: float
    settlement_time: Optional[datetime]

    threshold: Optional[float] = None
    direction: Optional[str] = None

    event_slug: Optional[str] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


def adapt_crypto_window(win: CryptoWindow) -> NormalizedMarket:
    return NormalizedMarket(
        platform="polymarket",
        ticker=win.market_id,
        title=f"BTC Up or Down 5m - {win.slug}",
        category="crypto",
        subcategory="btc-5m",
        yes_price=win.up_price,
        no_price=win.down_price,
        volume=win.volume,
        settlement_time=win.window_end,
        event_slug=win.slug,
        window_start=win.window_start,
        window_end=win.window_end,
    )


async def load_all_markets(**kwargs) -> List[NormalizedMarket]:
    windows = await load_active_windows()
    return [adapt_crypto_window(w) for w in windows]
