"""Real-time crypto price feed from multiple exchanges with technical indicators."""
import httpx
import logging
import math
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

BINANCE_ENDPOINT = "https://api.binance.com/api/v3"
BYBIT_ENDPOINT = "https://api.bybit.com/v5/market"
COINBASE_ENDPOINT = "https://api.exchange.coinbase.com"
KRAKEN_ENDPOINT = "https://api.kraken.com/0/public"

_candle_cache: Dict[str, Any] = {"data": None, "ts": 0.0}
_CANDLE_TTL = 30.0


@dataclass
class TechnicalSnapshot:
    """Real-time technical indicators derived from 1-minute candles."""
    rsi: float = 50.0
    momentum_1m: float = 0.0
    momentum_5m: float = 0.0
    momentum_15m: float = 0.0
    vwap: float = 0.0
    vwap_deviation: float = 0.0
    sma_crossover: float = 0.0
    volatility: float = 0.0
    price: float = 0.0
    source: str = "binance"


async def retrieve_candles(limit: int = 60) -> Optional[List[list]]:
    """
    Pull recent 1-minute candles for BTC/USD from the best available exchange.
    Cascade: Coinbase → Kraken → Binance → Bybit.
    """
    now = time.time()
    if _candle_cache["data"] is not None and (now - _candle_cache["ts"]) < _CANDLE_TTL:
        return _candle_cache["data"]

    async with httpx.AsyncClient(timeout=10.0) as http:
        # Primary: Coinbase
        try:
            import datetime as _dt
            end = _dt.datetime.now(_dt.timezone.utc)
            start = end - _dt.timedelta(minutes=limit)
            resp = await http.get(
                f"{COINBASE_ENDPOINT}/products/BTC-USD/candles",
                params={
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "granularity": 60,
                },
            )
            resp.raise_for_status()
            rows = resp.json()
            rows = list(reversed(rows))
            candles = [
                [int(r[0]) * 1000, str(r[3]), str(r[2]), str(r[1]), str(r[4]), str(r[5])]
                for r in rows
            ]
            _candle_cache["data"] = candles
            _candle_cache["ts"] = now
            _candle_cache["_source"] = "coinbase"
            return candles
        except Exception as exc:
            logger.warning(f"Coinbase candle fetch failed, trying Kraken: {exc}")

        # Fallback 1: Kraken
        try:
            resp = await http.get(
                f"{KRAKEN_ENDPOINT}/OHLC",
                params={"pair": "XBTUSD", "interval": 1},
            )
            resp.raise_for_status()
            body = resp.json()
            result = body.get("result", {})
            ohlc_key = [k for k in result if k != "last"]
            if ohlc_key:
                rows = result[ohlc_key[0]]
                rows = rows[-limit:]
                candles = [
                    [int(r[0]) * 1000, str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[6])]
                    for r in rows
                ]
                _candle_cache["data"] = candles
                _candle_cache["ts"] = now
                _candle_cache["_source"] = "kraken"
                return candles
        except Exception as exc:
            logger.warning(f"Kraken candle fetch failed, trying Binance: {exc}")

        # Fallback 2: Binance
        try:
            resp = await http.get(
                f"{BINANCE_ENDPOINT}/klines",
                params={"symbol": "BTCUSDT", "interval": "1m", "limit": limit},
            )
            resp.raise_for_status()
            candles = resp.json()
            _candle_cache["data"] = candles
            _candle_cache["ts"] = now
            _candle_cache["_source"] = "binance"
            return candles
        except Exception as exc:
            logger.warning(f"Binance candle fetch failed, trying Bybit: {exc}")

        # Fallback 3: Bybit
        try:
            resp = await http.get(
                f"{BYBIT_ENDPOINT}/kline",
                params={
                    "category": "spot",
                    "symbol": "BTCUSDT",
                    "interval": "1",
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            body = resp.json()
            rows = body.get("result", {}).get("list", [])
            rows = list(reversed(rows))
            candles = [
                [int(r[0]), r[1], r[2], r[3], r[4], r[5]]
                for r in rows
            ]
            _candle_cache["data"] = candles
            _candle_cache["ts"] = now
            _candle_cache["_source"] = "bybit"
            return candles
        except Exception as exc:
            logger.error(f"All candle sources failed: {exc}")

        return None


def _wilder_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains = [d if d > 0 else 0.0 for d in deltas[:period]]
    losses = [-d if d < 0 else 0.0 for d in deltas[:period]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for d in deltas[period:]:
        gain = d if d > 0 else 0.0
        loss = -d if d < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


async def snapshot_technicals() -> Optional[TechnicalSnapshot]:
    """
    Build a full technical snapshot from 60 one-minute candles.
    Returns None if insufficient data.
    """
    candles = await retrieve_candles(limit=60)
    if not candles or len(candles) < 20:
        logger.warning("Insufficient candle data for technical snapshot")
        return None

    closes = [float(c[4]) for c in candles]
    volumes = [float(c[5]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]

    spot = closes[-1]

    rsi = _wilder_rsi(closes, 14)

    def pct_delta(lookback: int) -> float:
        if len(closes) > lookback and closes[-1 - lookback] > 0:
            return (closes[-1] - closes[-1 - lookback]) / closes[-1 - lookback] * 100
        return 0.0

    mom_1m = pct_delta(1)
    mom_5m = pct_delta(5)
    mom_15m = pct_delta(15)

    vwap_len = min(30, len(closes))
    typical = [(highs[-i] + lows[-i] + closes[-i]) / 3 for i in range(1, vwap_len + 1)]
    vwap_vol = [volumes[-i] for i in range(1, vwap_len + 1)]
    total_vol = sum(vwap_vol)
    if total_vol > 0:
        vwap = sum(tp * v for tp, v in zip(typical, vwap_vol)) / total_vol
    else:
        vwap = spot
    vwap_dev = (spot - vwap) / vwap * 100 if vwap > 0 else 0.0

    sma_short = sum(closes[-5:]) / 5 if len(closes) >= 5 else spot
    sma_long = sum(closes[-15:]) / 15 if len(closes) >= 15 else spot
    sma_cross = (sma_short - sma_long) / spot * 100 if spot > 0 else 0.0

    vol_len = min(30, len(closes) - 1)
    ret_series = [
        (closes[-i] - closes[-i - 1]) / closes[-i - 1]
        for i in range(1, vol_len + 1)
        if closes[-i - 1] > 0
    ]
    if ret_series:
        mean_ret = sum(ret_series) / len(ret_series)
        var = sum((r - mean_ret) ** 2 for r in ret_series) / len(ret_series)
        vol = math.sqrt(var) * 100
    else:
        vol = 0.0

    feed_source = _candle_cache.get("_source", "unknown")

    return TechnicalSnapshot(
        rsi=rsi,
        momentum_1m=mom_1m,
        momentum_5m=mom_5m,
        momentum_15m=mom_15m,
        vwap=vwap,
        vwap_deviation=vwap_dev,
        sma_crossover=sma_cross,
        volatility=vol,
        price=spot,
        source=feed_source,
    )


COINGECKO_ENDPOINT = "https://api.coingecko.com/api/v3"


@dataclass
class SpotQuote:
    """Snapshot of a crypto asset's spot price and market data."""
    symbol: str
    name: str
    current_price: float
    price_24h_ago: float
    change_24h: float
    change_7d: float
    market_cap: float
    volume_24h: float
    last_updated: datetime


TICKER_TO_CG_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "MATIC": "matic-network",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
}


async def get_spot_price(symbol: str) -> Optional[SpotQuote]:
    """
    Retrieve current spot price for a crypto asset via CoinGecko.
    """
    ticker = symbol.upper()
    cg_id = TICKER_TO_CG_ID.get(ticker, symbol.lower())

    url = f"{COINGECKO_ENDPOINT}/coins/{cg_id}"
    params = {
        "localization": "false",
        "tickers": "false",
        "market_data": "true",
        "community_data": "false",
        "developer_data": "false"
    }

    async with httpx.AsyncClient() as http:
        try:
            resp = await http.get(url, params=params, timeout=10.0)
            resp.raise_for_status()
            body = resp.json()

            mkt = body.get("market_data", {})
            spot = mkt.get("current_price", {}).get("usd", 0)
            pct_24h = mkt.get("price_change_percentage_24h", 0)
            pct_7d = mkt.get("price_change_percentage_7d", 0)

            prev_24h = spot / (1 + pct_24h / 100) if pct_24h else spot

            return SpotQuote(
                symbol=ticker,
                name=body.get("name", ticker),
                current_price=spot,
                price_24h_ago=prev_24h,
                change_24h=pct_24h or 0,
                change_7d=pct_7d or 0,
                market_cap=mkt.get("market_cap", {}).get("usd", 0),
                volume_24h=mkt.get("total_volume", {}).get("usd", 0),
                last_updated=datetime.utcnow()
            )

        except httpx.HTTPStatusError as exc:
            logger.warning(f"CoinGecko API error for {symbol}: {exc.response.status_code}")
            return None
        except Exception as exc:
            logger.error(f"Error fetching spot price for {symbol}: {exc}")
            return None


async def batch_spot_quotes(symbols: List[str]) -> Dict[str, SpotQuote]:
    """Fetch prices for multiple crypto assets in a single CoinGecko call."""
    cg_ids = [TICKER_TO_CG_ID.get(s.upper(), s.lower()) for s in symbols]

    url = f"{COINGECKO_ENDPOINT}/coins/markets"
    params = {
        "vs_currency": "usd",
        "ids": ",".join(cg_ids),
        "order": "market_cap_desc",
        "sparkline": "false",
        "price_change_percentage": "24h,7d"
    }

    async with httpx.AsyncClient() as http:
        try:
            resp = await http.get(url, params=params, timeout=15.0)
            resp.raise_for_status()
            body = resp.json()

            results = {}
            for coin in body:
                ticker = coin.get("symbol", "").upper()
                spot = coin.get("current_price", 0)
                pct_24h = coin.get("price_change_percentage_24h", 0) or 0
                pct_7d = coin.get("price_change_percentage_7d_in_currency", 0) or 0

                prev_24h = spot / (1 + pct_24h / 100) if pct_24h else spot

                results[ticker] = SpotQuote(
                    symbol=ticker,
                    name=coin.get("name", ticker),
                    current_price=spot,
                    price_24h_ago=prev_24h,
                    change_24h=pct_24h,
                    change_7d=pct_7d,
                    market_cap=coin.get("market_cap", 0) or 0,
                    volume_24h=coin.get("total_volume", 0) or 0,
                    last_updated=datetime.utcnow()
                )

            return results

        except Exception as exc:
            logger.error(f"Error fetching batch spot quotes: {exc}")
            return {}
