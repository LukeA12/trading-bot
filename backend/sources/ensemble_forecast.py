"""Ensemble weather forecast provider via Open-Meteo API and NWS observations."""
import httpx
import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
import statistics
import time

logger = logging.getLogger("trading_bot")

STATION_REGISTRY: Dict[str, dict] = {
    "nyc": {
        "name": "New York City",
        "lat": 40.7128,
        "lon": -74.0060,
        "nws_station": "KNYC",
        "nws_office": "OKX",
        "nws_gridpoint": "OKX/33,37",
    },
    "chicago": {
        "name": "Chicago",
        "lat": 41.8781,
        "lon": -87.6298,
        "nws_station": "KORD",
        "nws_office": "LOT",
        "nws_gridpoint": "LOT/75,72",
    },
    "miami": {
        "name": "Miami",
        "lat": 25.7617,
        "lon": -80.1918,
        "nws_station": "KMIA",
        "nws_office": "MFL",
        "nws_gridpoint": "MFL/75,53",
    },
    "los_angeles": {
        "name": "Los Angeles",
        "lat": 34.0522,
        "lon": -118.2437,
        "nws_station": "KLAX",
        "nws_office": "LOX",
        "nws_gridpoint": "LOX/154,44",
    },
    "denver": {
        "name": "Denver",
        "lat": 39.7392,
        "lon": -104.9903,
        "nws_station": "KDEN",
        "nws_office": "BOU",
        "nws_gridpoint": "BOU/62,60",
    },
}


@dataclass
class WeatherEnsemble:
    """Multi-member ensemble forecast with per-member temperature arrays."""
    city_key: str
    city_name: str
    target_date: date
    member_highs: List[float]
    member_lows: List[float]
    mean_high: float = 0.0
    std_high: float = 0.0
    mean_low: float = 0.0
    std_low: float = 0.0
    num_members: int = 0
    fetched_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        if self.member_highs:
            self.mean_high = statistics.mean(self.member_highs)
            self.std_high = statistics.stdev(self.member_highs) if len(self.member_highs) > 1 else 0.0
            self.num_members = len(self.member_highs)
        if self.member_lows:
            self.mean_low = statistics.mean(self.member_lows)
            self.std_low = statistics.stdev(self.member_lows) if len(self.member_lows) > 1 else 0.0

    def probability_high_above(self, threshold_f: float) -> float:
        if not self.member_highs:
            return 0.5
        count = sum(1 for h in self.member_highs if h > threshold_f)
        return count / len(self.member_highs)

    def probability_high_below(self, threshold_f: float) -> float:
        return 1.0 - self.probability_high_above(threshold_f)

    def probability_low_above(self, threshold_f: float) -> float:
        if not self.member_lows:
            return 0.5
        count = sum(1 for l in self.member_lows if l > threshold_f)
        return count / len(self.member_lows)

    def probability_low_below(self, threshold_f: float) -> float:
        return 1.0 - self.probability_low_above(threshold_f)

    @property
    def ensemble_agreement(self) -> float:
        if not self.member_highs:
            return 0.5
        median = statistics.median(self.member_highs)
        above = sum(1 for h in self.member_highs if h > median)
        frac = above / len(self.member_highs)
        return max(frac, 1 - frac)


_ensemble_cache: Dict[str, tuple] = {}
_ENSEMBLE_TTL = 900


def _c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


async def load_ensemble(city_key: str, target_date: Optional[date] = None) -> Optional[WeatherEnsemble]:
    """
    Pull ensemble forecast from Open-Meteo (GFS 31-member).
    Returns per-member daily max/min temperatures in Fahrenheit.
    """
    if city_key not in STATION_REGISTRY:
        logger.warning(f"Unknown city key: {city_key}")
        return None

    if target_date is None:
        target_date = date.today()

    cache_id = f"{city_key}_{target_date.isoformat()}"
    now = time.time()
    if cache_id in _ensemble_cache:
        cached_ts, cached_data = _ensemble_cache[cache_id]
        if now - cached_ts < _ENSEMBLE_TTL:
            return cached_data

    station = STATION_REGISTRY[city_key]

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            query = {
                "latitude": station["lat"],
                "longitude": station["lon"],
                "daily": "temperature_2m_max,temperature_2m_min",
                "temperature_unit": "fahrenheit",
                "start_date": target_date.isoformat(),
                "end_date": target_date.isoformat(),
                "models": "gfs_seamless",
            }

            resp = await http.get(
                "https://ensemble-api.open-meteo.com/v1/ensemble",
                params=query,
            )
            resp.raise_for_status()
            payload = resp.json()

            daily = payload.get("daily", {})

            highs = []
            lows = []

            for key, values in daily.items():
                if not isinstance(values, list) or not values:
                    continue
                val = values[0]
                if val is None:
                    continue
                if "temperature_2m_max" in key:
                    highs.append(float(val))
                elif "temperature_2m_min" in key:
                    lows.append(float(val))

            if not highs:
                logger.warning(f"No ensemble data for {city_key} on {target_date}")
                return None

            ensemble = WeatherEnsemble(
                city_key=city_key,
                city_name=station["name"],
                target_date=target_date,
                member_highs=highs,
                member_lows=lows,
            )

            _ensemble_cache[cache_id] = (now, ensemble)
            logger.info(f"Ensemble forecast for {station['name']} on {target_date}: "
                        f"High {ensemble.mean_high:.1f}F +/- {ensemble.std_high:.1f}F "
                        f"({ensemble.num_members} members)")

            return ensemble

    except Exception as exc:
        logger.warning(f"Failed to fetch ensemble forecast for {city_key}: {exc}")
        return None


async def load_observed_temp(city_key: str, target_date: Optional[date] = None) -> Optional[Dict[str, float]]:
    """
    Retrieve observed temperature from NWS API for position settlement.
    Returns dict with 'high' and 'low' in Fahrenheit, or None.
    """
    if city_key not in STATION_REGISTRY:
        return None

    station = STATION_REGISTRY[city_key]
    if target_date is None:
        target_date = date.today()

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            station_id = station["nws_station"]
            url = f"https://api.weather.gov/stations/{station_id}/observations"
            headers = {"User-Agent": "(trading-bot, contact@example.com)"}

            start = datetime.combine(target_date, datetime.min.time()).isoformat() + "Z"
            end = datetime.combine(target_date + timedelta(days=1), datetime.min.time()).isoformat() + "Z"

            resp = await http.get(url, params={"start": start, "end": end}, headers=headers)
            resp.raise_for_status()
            payload = resp.json()

            features = payload.get("features", [])
            if not features:
                return None

            readings = []
            for obs in features:
                props = obs.get("properties", {})
                temp_c = props.get("temperature", {}).get("value")
                if temp_c is not None:
                    readings.append(_c_to_f(temp_c))

            if not readings:
                return None

            return {
                "high": max(readings),
                "low": min(readings),
            }

    except Exception as exc:
        logger.warning(f"Failed to fetch NWS observations for {city_key}: {exc}")
        return None
