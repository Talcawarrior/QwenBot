"""
Database module with SQLite WAL mode and proper JSON serialization.
"""

import json
import logging
import os
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
 create_engine,
    event,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker

from config import Config

logger = logging.getLogger("DATABASE")

Base = declarative_base()


# Enums


class BetStatus(str, PyEnum):
    """Status enum for bet lifecycle."""
    OPEN = "open"
    ACTIVE = "active"
    WON = "won"
    LOST = "lost"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class Outcome(str, PyEnum):
    """Outcome enum for bet direction."""
    YES = "YES"
    NO = "NO"


class MarketType(str, PyEnum):
    """Market type enum for classification."""
    HIGH = "HIGH"
    LOW = "LOW"
    RANGE = "RANGE"


# Models


class Portfolio(Base):
    """Portfolio model tracking overall financial state."""
    __tablename__ = "portfolio"

    id = Column(Integer, primary_key=True)
    initial_value = Column(Float, default=1000.0)
    current_value = Column(Float, default=1000.0)
    cash_balance = Column(Float, default=1000.0)
    total_value = Column(Float, default=1000.0)
    total_realized_pnl = Column(Float, default=0.0)
    total_won = Column(Integer, default=0)
    total_lost = Column(Integer, default=0)
    daily_pnl = Column(Float, default=0.0)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Market(Base):
    """Market model for weather prediction markets."""
    __tablename__ = "markets"

    id = Column(Integer, primary_key=True)
    market_id = Column(String, unique=True, nullable=False)
    event_id = Column(String, nullable=False)
    title = Column(String)
    question = Column(String)
    city_code = Column(String, default="")
    city_name = Column(String)
    city = Column(String)  # for compatibility with main.py bet.city etc
    country = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    strike_temp = Column(Float)
    threshold_type = Column(String)  # "above", "below", "or_below", "or_above"
    range_type = Column(String)  # "HIGH", "LOW", "RANGE"
    resolution_date = Column(DateTime)
    date = Column(DateTime)  # compatibility
    outcome_type = Column(String)  # "YES" or "NO"
    yes_price = Column(Float, default=0.5)
    no_price = Column(Float, default=0.5)
    current_yes_bid = Column(Float, default=0.5)
    current_no_bid = Column(Float, default=0.5)
    volume = Column(Float, default=0.0)
    status = Column(String, default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Bet(Base):
    """Bet model for individual positions."""
    __tablename__ = "bets"

    id = Column(Integer, primary_key=True)
    market_id = Column(String, nullable=False)
    city_code = Column(String)
    city = Column(String)  # compatibility
    outcome = Column(String)  # "YES" or "NO"
    stake = Column(Float)
    stake_amount = Column(Float, default=0.0)
    entry_price = Column(Float)
    shares = Column(Float)
    current_price = Column(Float, default=0.5)
    pnl = Column(Float, default=0.0)
    unrealized_pnl = Column(Float, default=0.0)
    fair_value = Column(Float, default=0.0)
    expected_value = Column(Float, default=0.0)
    strike_temp = Column(Float)
    bet_type = Column(String)  # YES/NO or HIGH/LOW
    side = Column(String)  # YES/NO/HIGH/LOW
    realized_pnl = Column(Float, default=0.0)
    status = Column(
        String, default="open"
    )  # open, won, lost, cancelled, active, settled
    ladder_data = Column(Text)  # JSON serialized
    result_data = Column(Text)  # JSON serialized
    placed_at = Column(DateTime, default=datetime.utcnow)
    settled_at = Column(DateTime, nullable=True)


class ModelPerformance(Base):
    """Model performance tracking for SIA optimization."""
    __tablename__ = "model_performance"

    id = Column(Integer, primary_key=True)
    model_name = Column(String, nullable=False)
    total_predictions = Column(Integer, default=0)
    correct_predictions = Column(Integer, default=0)
    accuracy = Column(Float, default=0.0)
    num_predictions = Column(Integer, default=0)
    brier_score = Column(Float, default=0.0)
    weight = Column(Float, default=0.0)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    recorded_at = Column(DateTime, default=datetime.utcnow)


# Database setup with WAL mode - use Config for absolute path + dir create
DB_PATH = Config.DB_PATH


def get_engine():
    """Create engine with WAL mode enabled."""
    # Ensure data dir exists (fix relative path startup crash)
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    eng = create_engine(
        f"sqlite:///{DB_PATH}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        echo=Config.DB_ECHO,
    )

    @event.listens_for(eng, "connect")
    def set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=10000")
        cursor.close()

    return eng


engine = get_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)  # pylint: disable=invalid-name


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized at %s with WAL mode", DB_PATH)


def get_db_session() -> Session:
    """Get a new database session."""
    return SessionLocal()


def get_db_session_factory():
    """Return the SessionLocal factory for per-task session creation."""
    return SessionLocal


def close_db_session(session: Session):
    """Close database session."""
    session.close()


# Helper functions for JSON serialization
def serialize_json(data) -> str:
    """Serialize Python object to JSON string."""
    if data is None:
        return "{}"
    return json.dumps(data)


def deserialize_json(json_str: str):
    """Deserialize JSON string to Python object."""
    if not json_str:
        return {}
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {}
