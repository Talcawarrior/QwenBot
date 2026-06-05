"""Database models for QwenBot."""

from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


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
    city = Column(String)  # for compatibility
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
    status = Column(String, default="open")  # open, won, lost, cancelled, active, settled
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
