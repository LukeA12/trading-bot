"""Kalshi exchange API connector with RSA-PSS signature authentication."""
import base64
import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from backend.env import cfg

logger = logging.getLogger("trading_bot")

KALSHI_ENDPOINT = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiConnector:
    """Async connector for Kalshi exchange with RSA-PSS auth."""

    def __init__(self):
        self._rsa_key = None

    def _load_key(self):
        if self._rsa_key is not None:
            return self._rsa_key

        key_path = cfg.KALSHI_PRIVATE_KEY_PATH
        if not key_path:
            raise ValueError("KALSHI_PRIVATE_KEY_PATH not configured")

        pem_bytes = Path(key_path).expanduser().read_bytes()
        self._rsa_key = serialization.load_pem_private_key(pem_bytes, password=None)
        return self._rsa_key

    def _build_auth_headers(self, method: str, path: str) -> Dict[str, str]:
        ts_ms = str(int(time.time() * 1000))
        msg = f"{ts_ms}{method.upper()}{path}"

        rsa_key = self._load_key()
        sig = rsa_key.sign(
            msg.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )

        return {
            "KALSHI-ACCESS-KEY": cfg.KALSHI_API_KEY_ID,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
            "Content-Type": "application/json",
        }

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> dict:
        full_path = f"/trade-api/v2{path}"
        url = f"{KALSHI_ENDPOINT}{path}"
        headers = self._build_auth_headers("GET", full_path)

        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()

    async def get_markets(self, params: Optional[Dict[str, Any]] = None) -> dict:
        return await self.get("/markets", params=params)

    async def get_market(self, ticker: str) -> dict:
        return await self.get(f"/markets/{ticker}")

    async def get_balance(self) -> dict:
        return await self.get("/portfolio/balance")


def kalshi_configured() -> bool:
    return bool(cfg.KALSHI_API_KEY_ID and cfg.KALSHI_PRIVATE_KEY_PATH)
