"""Polymarket weather temperature contract discovery and parsing."""
import httpx
import re
import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

logger = logging.getLogger("trading_bot")

CITY_ALIASES = {
    "new york": "nyc",
    "nyc": "nyc",
    "new york city": "nyc",
    "chicago": "chicago",
    "miami": "miami",
    "los angeles": "los_angeles",
    "la": "los_angeles",
    "denver": "denver",
}

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


@dataclass
class TempContract:
    """A weather temperature prediction contract."""
    slug: str
    market_id: str
    platform: str
    title: str
    city_key: str
    city_name: str
    target_date: date
    threshold_f: float
    metric: str
    direction: str
    yes_price: float
    no_price: float
    volume: float = 0.0
    closed: bool = False
    # Set when market asks about a range band (e.g. "between 70-71°F")
    range_low_f: Optional[float] = None
    range_high_f: Optional[float] = None

    @property
    def is_range_contract(self) -> bool:
        return self.range_low_f is not None and self.range_high_f is not None


def _parse_temp_title(title: str) -> Optional[dict]:
    """Extract structured parameters from a weather market title string."""
    lower = title.lower()

    if not any(kw in lower for kw in [
        "temperature", "temp", "°f", "degrees", "high", "low",
        "exceed", "forecast", "warming", "cooling", "heat",
    ]):
        return None

    city_key = None
    city_name = None
    for alias, key in sorted(CITY_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in lower:
            city_key = key
            from backend.sources.ensemble_forecast import STATION_REGISTRY
            city_name = STATION_REGISTRY[key]["name"]
            break

    if not city_key:
        return None

    # Detect range contracts first: "between X-Y°F" or "X to Y°F"
    # Require an explicit separator (dash or "to") to avoid matching single numbers
    range_low_f = None
    range_high_f = None
    range_match = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*°?\s*f', lower)
    if not range_match:
        range_match = re.search(r'(\d+)\s+to\s+(\d+)\s*°?\s*f', lower)
    if range_match and range_match.group(1) != range_match.group(2):
        range_low_f = float(range_match.group(1))
        range_high_f = float(range_match.group(2))
        threshold_f = range_high_f  # use upper bound as threshold
    else:
        temp_match = re.search(r'(\d+)\s*°?\s*f', lower)
        if not temp_match:
            temp_match = re.search(r'(\d+)\s*degrees', lower)
        if not temp_match:
            return None
        threshold_f = float(temp_match.group(1))

    # Detect metric — check for "lowest" / "highest" before "low" / "high" to avoid
    # matching "low" inside "lowest" incorrectly for direction
    metric = "high"
    if any(kw in lower for kw in ["lowest", "low temperature", "low temp", "overnight low", "minimum"]):
        metric = "low"
    elif "low" in lower and "high" not in lower:
        metric = "low"

    direction = "above"
    if any(kw in lower for kw in ["below", "under", "less than", "drop below", "or lower", "or cooler"]):
        direction = "below"
    elif range_low_f is not None:
        # Range contracts are implicitly "in-band" — treat as above lower bound
        direction = "above"

    target = _parse_date_from_text(lower)
    if not target:
        return None

    return {
        "city_key": city_key,
        "city_name": city_name,
        "threshold_f": threshold_f,
        "metric": metric,
        "direction": direction,
        "target_date": target,
        "range_low_f": range_low_f,
        "range_high_f": range_high_f,
    }


def _parse_date_from_text(text: str) -> Optional[date]:
    today = date.today()
    # Strip ordinal suffixes so "May 5th" and "May 5" both parse
    text = re.sub(r'(\d+)(?:st|nd|rd|th)\b', r'\1', text)
    month_names = "|".join(MONTH_MAP.keys())

    for match in re.finditer(rf'({month_names})\s+(\d{{1,2}})(?:\s*,?\s*(\d{{4}}))?', text):
        mon_str = match.group(1)
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year

        month = MONTH_MAP.get(mon_str)
        if month and 1 <= day <= 31:
            try:
                return date(year, month, day)
            except ValueError:
                continue

    match = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{4}))?', text)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        try:
            return date(year, month, day)
        except ValueError:
            pass

    return None


async def load_poly_temp_contracts(city_keys: Optional[List[str]] = None) -> List[TempContract]:
    """
    Search Polymarket for active temperature prediction contracts.
    Parses titles to extract city, threshold, metric, and date.
    """
    contracts = []

    seen_ids: set = set()

    def _add_contract(contract):
        if contract and contract.market_id not in seen_ids:
            seen_ids.add(contract.market_id)
            contracts.append(contract)

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            # tag_slug=weather is the only param the Gamma API actually filters on.
            # tag=Weather / q=... / slug_contains=... are all silently ignored.
            # Fetch up to 300 weather events across 3 pages.
            for offset in [0, 100, 200]:
                try:
                    resp = await http.get(
                        "https://gamma-api.polymarket.com/events",
                        params={
                            "closed": "false",
                            "limit": 100,
                            "offset": offset,
                            "tag_slug": "weather",
                        },
                    )
                    resp.raise_for_status()
                    page = resp.json()
                    if not page:
                        break
                    for event in page:
                        event_slug = event.get("slug", "")
                        for mkt_data in event.get("markets", []):
                            _add_contract(_extract_poly_temp_contract(mkt_data, event_slug, city_keys))
                except Exception as exc:
                    logger.debug(f"Weather page offset={offset} failed: {exc}")
                    break

    except Exception as exc:
        logger.warning(f"Failed to fetch temperature contracts: {exc}")

    logger.info(f"Found {len(contracts)} weather temperature contracts")
    return contracts


def _extract_poly_temp_contract(
    mkt_data: dict,
    event_slug: str,
    city_keys: Optional[List[str]] = None,
) -> Optional[TempContract]:
    question = mkt_data.get("question", "") or mkt_data.get("groupItemTitle", "")
    if not question:
        return None

    parsed = _parse_temp_title(question)
    if not parsed:
        return None

    if city_keys and parsed["city_key"] not in city_keys:
        return None

    # Skip same-day contracts — the market has live observations while our
    # ensemble is a morning forecast. The market always has better data by mid-day.
    if parsed["target_date"] <= date.today():
        return None

    outcome_prices = mkt_data.get("outcomePrices", [])
    if isinstance(outcome_prices, str):
        import json
        try:
            outcome_prices = json.loads(outcome_prices)
        except Exception:
            outcome_prices = []

    if not outcome_prices or len(outcome_prices) < 2:
        return None

    try:
        yes_p = float(outcome_prices[0])
        no_p = float(outcome_prices[1])
    except (ValueError, IndexError):
        return None

    if mkt_data.get("closed", False):
        return None
    # Skip contracts where the market is extremely out-of-the-money — these are
    # narrow range bands far from expected temperature and our model cannot price them.
    if yes_p > 0.98 or yes_p < 0.08:
        return None

    vol = float(mkt_data.get("volume", 0) or 0)

    return TempContract(
        slug=event_slug,
        market_id=str(mkt_data.get("id", "")),
        platform="polymarket",
        title=question,
        city_key=parsed["city_key"],
        city_name=parsed["city_name"],
        target_date=parsed["target_date"],
        threshold_f=parsed["threshold_f"],
        metric=parsed["metric"],
        direction=parsed["direction"],
        yes_price=yes_p,
        no_price=no_p,
        volume=vol,
        range_low_f=parsed.get("range_low_f"),
        range_high_f=parsed.get("range_high_f"),
    )
