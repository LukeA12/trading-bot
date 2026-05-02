"""Kalshi weather temperature contract fetcher."""
import logging
import re
from datetime import date, datetime
from typing import Dict, List, Optional

from backend.sources.kalshi_api import KalshiConnector, kalshi_configured
from backend.sources.polymarket_weather import TempContract

logger = logging.getLogger("trading_bot")

CITY_SERIES: Dict[str, str] = {
    "nyc": "KXHIGHNY",
    "chicago": "KXHIGHCHI",
    "miami": "KXHIGHMIA",
    "los_angeles": "KXHIGHLAX",
    "denver": "KXHIGHDEN",
}

CITY_LABELS: Dict[str, str] = {
    "nyc": "New York",
    "chicago": "Chicago",
    "miami": "Miami",
    "los_angeles": "Los Angeles",
    "denver": "Denver",
}

MONTH_ABBR = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def _decode_kalshi_ticker(ticker: str, city_key: str) -> Optional[dict]:
    match = re.match(
        r'^[A-Z]+-(\d{2})([A-Z]{3})(\d{2})-([BT])([\d.]+)$',
        ticker,
    )
    if not match:
        return None

    yy = int(match.group(1))
    mon_str = match.group(2)
    dd = int(match.group(3))
    boundary = match.group(4)
    threshold = float(match.group(5))

    month = MONTH_ABBR.get(mon_str)
    if not month:
        return None

    year = 2000 + yy
    try:
        target = date(year, month, dd)
    except ValueError:
        return None

    return {
        "target_date": target,
        "threshold_f": threshold,
        "metric": "high",
        "direction": "above" if boundary == "B" else "below",
    }


async def load_kalshi_temp_contracts(
    city_keys: Optional[List[str]] = None,
) -> List[TempContract]:
    """
    Fetch open weather temperature contracts from Kalshi.
    Handles cursor-based pagination across city series.
    """
    if not kalshi_configured():
        logger.info(
            "Kalshi weather contracts skipped: KALSHI_API_KEY_ID or "
            "KALSHI_PRIVATE_KEY_PATH not set in .env"
        )
        return []

    connector = KalshiConnector()
    contracts: List[TempContract] = []
    today = date.today()

    cities = city_keys or list(CITY_SERIES.keys())

    for city_key in cities:
        series = CITY_SERIES.get(city_key)
        if not series:
            continue

        label = CITY_LABELS.get(city_key, city_key)
        cursor = None

        try:
            while True:
                params = {
                    "series_ticker": series,
                    "status": "open",
                    "limit": 200,
                }
                if cursor:
                    params["cursor"] = cursor

                data = await connector.get_markets(params)
                raw = data.get("markets", [])

                for m in raw:
                    ticker = m.get("ticker", "")
                    parsed = _decode_kalshi_ticker(ticker, city_key)
                    if not parsed:
                        continue

                    if parsed["target_date"] < today:
                        continue

                    yes_p = (m.get("yes_ask") or 0) / 100.0
                    no_p = (m.get("no_ask") or 0) / 100.0

                    if yes_p <= 0:
                        yes_p = (m.get("last_price") or 50) / 100.0
                    if no_p <= 0:
                        no_p = 1.0 - yes_p

                    if yes_p > 0.98 or yes_p < 0.02:
                        continue

                    vol = float(m.get("volume", 0) or 0)

                    contracts.append(TempContract(
                        slug=ticker,
                        market_id=ticker,
                        platform="kalshi",
                        title=m.get("title", ticker),
                        city_key=city_key,
                        city_name=label,
                        target_date=parsed["target_date"],
                        threshold_f=parsed["threshold_f"],
                        metric=parsed["metric"],
                        direction=parsed["direction"],
                        yes_price=yes_p,
                        no_price=no_p,
                        volume=vol,
                    ))

                cursor = data.get("cursor")
                if not cursor or not raw:
                    break

        except Exception as exc:
            logger.warning(f"Failed to fetch Kalshi contracts for {city_key} ({series}): {exc}")

    logger.info(f"Found {len(contracts)} Kalshi weather contracts")
    return contracts
