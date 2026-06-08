"""Database setup with WAL mode and custom transaction sessions."""

import os
import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from config.settings import config
from database.models import Base

logger = logging.getLogger("DATABASE")
DB_PATH = config.DB_PATH


def get_engine():
    """Create database engine with optimized SQLite settings."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    eng = create_engine(
        f"sqlite:///{DB_PATH}",
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
        echo=config.DB_ECHO,
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
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized at %s with WAL mode", DB_PATH)


@contextmanager
def get_session():
    """Her işlem kendi session'ını alır, hata olursa rollback yapar."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_session():
    """Fallback compatibility method for legacy code."""
    return SessionLocal()


def get_db_session_factory():
    """Fallback compatibility method returning the raw sessionmaker factory."""
    return SessionLocal


def ensure_initial_portfolio():
    """Create Portfolio(id=1) with INITIAL_PORTFOLIO values if it does not exist.

    Called by both the FastAPI lifespan (server mode) and run_cli() (CLI mode)
    so that Portfolio(id=1) is guaranteed to exist before any bet is placed.
    Idempotent - safe to call multiple times.
    """
    from config.settings import config
    from database.models import Portfolio
    with get_session() as session:
        portfolio = session.query(Portfolio).filter(Portfolio.id == 1).first()
        if not portfolio:
            portfolio = Portfolio(
                id=1,
                initial_value=config.INITIAL_PORTFOLIO,
                current_value=config.INITIAL_PORTFOLIO,
                cash_balance=config.INITIAL_PORTFOLIO,
                total_value=config.INITIAL_PORTFOLIO,
                total_realized_pnl=0.0,
                total_won=0,
                total_lost=0,
                daily_pnl=0.0,
            )
            session.add(portfolio)
            session.commit()
            logger.info("ensure_initial_portfolio: Portfolio(id=1) created")
