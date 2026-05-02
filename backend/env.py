"""Application configuration loaded from environment variables."""
import os
from pydantic_settings import BaseSettings
from typing import Optional


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

    # LLM model selection
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    # LLM operational flags
    AI_LOG_ALL_CALLS: bool = True
    AI_DAILY_BUDGET_USD: float = 1.0

    # Execution parameters
    BTC_ENABLED: bool = True
    SIMULATION_MODE: bool = True
    INITIAL_BANKROLL: float = 10000.0
    KELLY_FRACTION: float = 0.15

    # Scheduling intervals
    SCAN_INTERVAL_SECONDS: int = 60
    SETTLEMENT_INTERVAL_SECONDS: int = 120
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
    WEATHER_MIN_EDGE_THRESHOLD: float = 0.04
    WEATHER_MAX_ENTRY_PRICE: float = 0.70
    WEATHER_MAX_TRADE_SIZE: float = 100.0
    WEATHER_CITIES: str = "nyc,chicago,miami,los_angeles,denver"

    class Config:
        env_file = ".env"


cfg = AppConfig()
