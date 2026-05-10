"""Application configuration loaded from environment variables and AWS Secrets Manager."""
import os
import json
import logging
from pydantic_settings import BaseSettings
from typing import Optional

logger = logging.getLogger(__name__)


def _load_aws_secrets() -> dict:
    """
    Fetch the trading bot secret bundle from AWS Secrets Manager.
    The secret is expected to be a JSON object with keys:
      GROQ_API_KEY, POLYMARKET_API_KEY, KALSHI_API_KEY_ID, ANTHROPIC_API_KEY
    Returns an empty dict if AWS is not available or the secret does not exist,
    so the app still boots locally from .env without AWS configured.
    """
    secret_name = os.environ.get("AWS_SECRET_NAME", "trading-bot/api-keys")
    region = os.environ.get("AWS_REGION", "us-east-1")

    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError

        client = boto3.client("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_name)
        secret_str = response.get("SecretString", "{}")
        return json.loads(secret_str)
    except ImportError:
        logger.debug("boto3 not installed — skipping AWS Secrets Manager")
        return {}
    except Exception as exc:
        # Covers NoCredentialsError, ClientError, network errors, etc.
        logger.debug("AWS Secrets Manager unavailable (%s) — falling back to .env", exc)
        return {}


# Fetch once at module load time, inject into the process environment so that
# pydantic-settings picks them up without any further changes to AppConfig.
_secrets = _load_aws_secrets()
for _k, _v in _secrets.items():
    if _v and not os.environ.get(_k):   # never overwrite values already set
        os.environ[_k] = str(_v)


class AppConfig(BaseSettings):
    """Runtime configuration for the trading platform."""

    # Persistence layer
    DATABASE_URL: str = "sqlite:///./tradingbot.db"

    # External platform credentials
    POLYMARKET_API_KEY: Optional[str] = None

    # Kalshi exchange
    KALSHI_API_KEY_ID: Optional[str] = None
    KALSHI_PRIVATE_KEY_PATH: Optional[str] = None
    KALSHI_ENABLED: bool = True

    # LLM providers
    GROQ_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None

    # LLM model selection
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    # LLM operational flags
    AI_LOG_ALL_CALLS: bool = True
    AI_DAILY_BUDGET_USD: float = 1.0

    # Execution parameters
    SIMULATION_MODE: bool = True
    INITIAL_BANKROLL: float = 10000.0
    KELLY_FRACTION: float = 0.15

    # Scheduling intervals
    SCAN_INTERVAL_SECONDS: int = 60
    SETTLEMENT_INTERVAL_SECONDS: int = 120
    BTC_ENABLED: bool = True
    BTC_PRICE_SOURCE: str = "coinbase"
    MIN_EDGE_THRESHOLD: float = 0.02
    MAX_ENTRY_PRICE: float = 0.55
    MAX_TRADES_PER_WINDOW: int = 1
    MAX_TOTAL_PENDING_TRADES: int = 20

    # Portfolio risk controls
    DAILY_LOSS_LIMIT: float = 300.0
    MAX_TRADE_SIZE: float = 75.0
    MIN_TIME_REMAINING: int = 60
    MAX_TIME_REMAINING: int = 1800

    # Composite signal weights
    WEIGHT_RSI: float = 0.20
    WEIGHT_MOMENTUM: float = 0.35
    WEIGHT_VWAP: float = 0.20
    WEIGHT_SMA: float = 0.15
    WEIGHT_MARKET_SKEW: float = 0.10

    # Liquidity filter
    MIN_MARKET_VOLUME: float = 100.0

    # Weather module
    WEATHER_ENABLED: bool = True
    WEATHER_SCAN_INTERVAL_SECONDS: int = 300
    WEATHER_SETTLEMENT_INTERVAL_SECONDS: int = 1800
    WEATHER_MIN_EDGE_THRESHOLD: float = 0.08
    WEATHER_MAX_ENTRY_PRICE: float = 0.70
    WEATHER_MAX_TRADE_SIZE: float = 100.0
    WEATHER_CITIES: str = "nyc,chicago,miami,los_angeles,denver"

    class Config:
        env_file = ".env"
        extra = "ignore"  # silently drop AWS_* and any other unknown env vars


cfg = AppConfig()
