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


def _parse_temp_title(title: str) -> Optional[dict]:
    """Extract structured parameters from a weather market title string."""
    lower = title.lower()

    if not any(kw in lower for kw in ["temperature", "temp", "°f", "degrees", "high", "low"]):
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

    temp_match = re.search(r'(\d+)\s*°?\s*f', lower)
    if not temp_match:
        temp_match = re.search(r'(\d+)\s*degrees', lower)
    if not temp_match:
        return None
    threshold_f = float(temp_match.group(1))

    metric = "high"
    if "low" in lower:
        metric = "low"

    direction = "above"
    if any(kw in lower for kw in ["below", "under", "less than", "drop below"]):
        direction = "below"

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
    }


def _parse_date_from_text(text: str) -> Optional[date]:
    today = date.today()
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

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            for search_term in ["temperature", "weather high", "weather low"]:
                try:
                    resp = await http.get(
                        "https://gamma-api.polymarket.com/events",
                        params={
                            "closed": "false",
                            "limit": 100,
                            "tag": "Weather",
                        }
                    )
                    resp.raise_for_status()
                    events = resp.json()

                    for event in events:
                        event_slug = event.get("slug", "")
                        for mkt_data in event.get("markets", []):
                            contract = _extract_poly_temp_contract(mkt_data, event_slug, city_keys)
                            if contract:
                                contracts.append(contract)

                except Exception as exc:
                    logger.debug(f"Temp contract search for '{search_term}' failed: {exc}")

            for slug_pattern in ["weather", "temperature", "temp-"]:
                try:
                    resp = await http.get(
                        "https://gamma-api.polymarket.com/events",
                        params={
                            "closed": "false",
                            "limit": 100,
                            "slug_contains": slug_pattern,
                        }
                    )
                    resp.raise_for_status()
                    events = resp.json()

                    for event in events:
                        event_slug = event.get("slug", "")
                        for mkt_data in event.get("markets", []):
                            contract = _extract_poly_temp_contract(mkt_data, event_slug, city_keys)
                            if contract and not any(c.market_id == contract.market_id for c in contracts):
                                contracts.append(contract)

                except Exception as exc:
                    logger.debug(f"Temp slug search for '{slug_pattern}' failed: {exc}")

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

    if parsed["target_date"] < date.today():
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
    if yes_p > 0.98 or yes_p < 0.02:
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
    )
