"""Persistence layer: ORM models, session management, and schema migration."""
from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, JSON, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import inspect
import enum

from backend.env import cfg

_engine = create_engine(
    cfg.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in cfg.DATABASE_URL else {}
)
DbSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
Base = declarative_base()


class Position(Base):
    """Recorded positions for portfolio tracking."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, index=True)
    market_ticker = Column(String, index=True)
    platform = Column(String)
    event_slug = Column(String, nullable=True)
    market_type = Column(String, default="btc", index=True)

    direction = Column(String)
    entry_price = Column(Float)
    size = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)

    settled = Column(Boolean, default=False)
    settlement_time = Column(DateTime, nullable=True)
    settlement_value = Column(Float, nullable=True)
    result = Column(String, default="pending")
    pnl = Column(Float, nullable=True)

    model_probability = Column(Float)
    market_price_at_entry = Column(Float)
    edge_at_entry = Column(Float)
    strategy = Column(Integer, default=1)


class PriceSnapshot(Base):
    """Cached price observations for momentum calculations."""
    __tablename__ = "btc_price_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    price = Column(Float)
    source = Column(String, default="coingecko")


class PortfolioState(Base):
    """Aggregate portfolio metrics and operational state."""
    __tablename__ = "bot_state"

    id = Column(Integer, primary_key=True)
    bankroll = Column(Float, default=10000.0)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    last_run = Column(DateTime, nullable=True)
    is_running = Column(Boolean, default=False)


class Opportunity(Base):
    """Generated market opportunities with prediction metadata."""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    market_ticker = Column(String, index=True)
    platform = Column(String)
    market_type = Column(String, default="btc", index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    direction = Column(String)
    model_probability = Column(Float)
    market_price = Column(Float)
    edge = Column(Float)
    confidence = Column(Float)

    kelly_fraction = Column(Float)
    suggested_size = Column(Float)

    sources = Column(JSON)
    reasoning = Column(String)

    executed = Column(Boolean, default=False)

    actual_outcome = Column(String, nullable=True)
    outcome_correct = Column(Boolean, nullable=True)
    settlement_value = Column(Float, nullable=True)
    settled_at = Column(DateTime, nullable=True)


class LLMLog(Base):
    """Audit trail for LLM API invocations."""
    __tablename__ = "ai_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    provider = Column(String, index=True)
    model = Column(String)

    prompt = Column(String)
    response = Column(String)
    call_type = Column(String, index=True)

    latency_ms = Column(Float)
    tokens_used = Column(Integer)
    cost_usd = Column(Float)

    related_market = Column(String, nullable=True)
    success = Column(Boolean, default=True)
    error = Column(String, nullable=True)


class ScanRecord(Base):
    """Audit trail for automated scan cycles."""
    __tablename__ = "scan_logs"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, unique=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    categories_scanned = Column(JSON)
    platforms_scanned = Column(JSON)

    markets_found = Column(Integer, default=0)
    signals_generated = Column(Integer, default=0)
    trades_executed = Column(Integer, default=0)

    ai_calls_made = Column(Integer, default=0)
    ai_cost_usd = Column(Float, default=0.0)

    success = Column(Boolean, default=True)
    error = Column(String, nullable=True)


def bootstrap_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(bind=_engine)
    migrate_schema()


def migrate_schema():
    """Apply incremental column additions for forward compatibility."""
    inspector = inspect(_engine)
    try:
        trade_cols = [col["name"] for col in inspector.get_columns("trades")]
    except Exception:
        return

    if "event_slug" not in trade_cols:
        stmt = "ALTER TABLE trades ADD COLUMN event_slug VARCHAR"
        if _engine.dialect.name not in ("sqlite", "mysql"):
            stmt = "ALTER TABLE trades ADD COLUMN IF NOT EXISTS event_slug VARCHAR"

        with _engine.connect() as conn:
            with conn.begin():
                conn.execute(text(stmt))

    if "market_type" not in trade_cols:
        with _engine.connect() as conn:
            with conn.begin():
                conn.execute(text("ALTER TABLE trades ADD COLUMN market_type VARCHAR DEFAULT 'btc'"))

    if "strategy" not in trade_cols:
        with _engine.connect() as conn:
            with conn.begin():
                conn.execute(text("ALTER TABLE trades ADD COLUMN strategy INTEGER DEFAULT 1"))

    try:
        opp_cols = [col["name"] for col in inspector.get_columns("signals")]
    except Exception:
        opp_cols = []

    if opp_cols:
        with _engine.connect() as conn:
            for col_name, col_type in [
                ("actual_outcome", "TEXT"),
                ("outcome_correct", "BOOLEAN"),
                ("settlement_value", "FLOAT"),
                ("settled_at", "DATETIME"),
                ("market_type", "VARCHAR DEFAULT 'btc'"),
            ]:
                if col_name not in opp_cols:
                    try:
                        with conn.begin():
                            conn.execute(text(f"ALTER TABLE signals ADD COLUMN {col_name} {col_type}"))
                    except Exception:
                        pass


def db_session():
    """Yield a database session for request-scoped dependency injection."""
    session = DbSession()
    try:
        yield session
    finally:
        session.close()
