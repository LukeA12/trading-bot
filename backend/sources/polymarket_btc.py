"""Polymarket BTC 5-minute window fetcher and parser."""
import httpx
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional, List
from dataclasses import dataclass

logger = logging.getLogger("trading_bot")

POLYMARKET_ENDPOINT = "https://gamma-api.polymarket.com"
BTC_SERIES_ID = "btc-up-or-down-5m"

_WINDOW_SLUG_PATTERN = re.compile(r"^btc-updown-5m-\d{10}$")


def is_valid_window_slug(slug: str) -> bool:
    return bool(_WINDOW_SLUG_PATTERN.match(slug))


@dataclass
class CryptoWindow:
    """Represents a single 5-minute crypto prediction window."""
    slug: str
    market_id: str
    up_price: float
    down_price: float
    window_start: datetime
    window_end: datetime
    volume: float
    closed: bool

    @property
    def event_slug(self) -> str:
        return self.slug

    @property
    def spread(self) -> float:
        return abs(1.0 - self.up_price - self.down_price)

    @property
    def time_until_end(self) -> float:
        now = datetime.now(timezone.utc)
        return (self.window_end - now).total_seconds()

    @property
    def is_active(self) -> bool:
        now = datetime.now(timezone.utc)
        return self.window_start <= now <= self.window_end and not self.closed

    @property
    def is_upcoming(self) -> bool:
        now = datetime.now(timezone.utc)
        return now < self.window_start and not self.closed


def _snap_to_5min(ts: float) -> int:
    return int(ts) // 300 * 300


def _expected_window_ids(count: int = 5) -> List[str]:
    now = time.time()
    boundary = _snap_to_5min(now)
    next_boundary = boundary + 300

    ids = []
    for i in range(count):
        end_ts = next_boundary + (i * 300)
        ids.append(f"btc-updown-5m-{end_ts}")

    return ids


def _extract_window(event: dict) -> Optional[CryptoWindow]:
    mkt_list = event.get("markets", [])
    if not mkt_list:
        return None

    mkt = mkt_list[0]

    raw_prices = mkt.get("outcomePrices", "")
    price_up = 0.5
    price_down = 0.5
    if raw_prices:
        try:
            parsed = json.loads(raw_prices) if isinstance(raw_prices, str) else raw_prices
            if isinstance(parsed, list) and len(parsed) >= 2:
                price_up = float(parsed[0])
                price_down = float(parsed[1])
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    slug = event.get("slug", "")
    start_raw = event.get("startDate") or mkt.get("startDate")
    end_raw = event.get("endDate") or mkt.get("endDate")

    win_start = datetime.now(timezone.utc)
    win_end = datetime.now(timezone.utc)

    if start_raw:
        try:
            win_start = datetime.fromisoformat(start_raw.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass

    if end_raw:
        try:
            win_end = datetime.fromisoformat(end_raw.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            pass

    return CryptoWindow(
        slug=slug,
        market_id=str(mkt.get("id", "")),
        up_price=price_up,
        down_price=price_down,
        window_start=win_start,
        window_end=win_end,
        volume=float(mkt.get("volume", 0) or 0),
        closed=bool(mkt.get("closed", False) or event.get("closed", False)),
    )


async def load_window_by_slug(slug: str) -> Optional[CryptoWindow]:
    if not is_valid_window_slug(slug):
        logger.debug(f"Rejected invalid window slug: {slug}")
        return None

    url = f"{POLYMARKET_ENDPOINT}/events"
    params = {"slug": slug}

    async with httpx.AsyncClient(timeout=10.0) as http:
        try:
            resp = await http.get(url, params=params)
            resp.raise_for_status()
            events = resp.json()

            if not events:
                return None

            event = events[0] if isinstance(events, list) else events
            return _extract_window(event)

        except Exception as exc:
            logger.debug(f"Failed to fetch window {slug}: {exc}")
            return None


async def load_active_windows() -> List[CryptoWindow]:
    """
    Retrieve current and upcoming 5-minute crypto prediction windows.
    Uses computed slug lookup with series search fallback.
    """
    windows: List[CryptoWindow] = []
    seen = set()

    expected = _expected_window_ids(count=6)
    for slug in expected:
        win = await load_window_by_slug(slug)
        if win and win.slug not in seen:
            seen.add(win.slug)
            windows.append(win)

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(
                f"{POLYMARKET_ENDPOINT}/events",
                params={
                    "active": "true",
                    "closed": "false",
                    "slug_contains": "btc-updown-5m",
                    "limit": 20,
                }
            )
            resp.raise_for_status()
            events = resp.json()

            for event in events:
                win = _extract_window(event)
                if win and win.slug not in seen and is_valid_window_slug(win.slug):
                    seen.add(win.slug)
                    windows.append(win)

    except Exception as exc:
        logger.debug(f"Series search fallback failed: {exc}")

    windows.sort(key=lambda w: w.window_end)
    windows = [w for w in windows if not w.closed]

    logger.info(f"Fetched {len(windows)} active crypto prediction windows")
    return windows


async def load_window_for_settlement(slug: str) -> Optional[CryptoWindow]:
    """Fetch a window including closed ones, for settlement purposes."""
    url = f"{POLYMARKET_ENDPOINT}/events"
    params = {"slug": slug}

    async with httpx.AsyncClient(timeout=10.0) as http:
        try:
            resp = await http.get(url, params=params)
            resp.raise_for_status()
            events = resp.json()

            if not events:
                return None

            event = events[0] if isinstance(events, list) else events
            return _extract_window(event)

        except Exception as exc:
            logger.warning(f"Failed to fetch window for settlement {slug}: {exc}")
            return None


if __name__ == "__main__":
    import asyncio

    async def test():
        print("Fetching active crypto prediction windows...")
        windows = await load_active_windows()
        print(f"Found {len(windows)} windows")

        for w in windows:
            print(f"\n  {w.slug}")
            print(f"  Up: {w.up_price:.2%} | Down: {w.down_price:.2%}")
            print(f"  Window: {w.window_start} -> {w.window_end}")
            print(f"  Volume: ${w.volume:,.0f}")
            print(f"  Active: {w.is_active} | Upcoming: {w.is_upcoming}")

    asyncio.run(test())
