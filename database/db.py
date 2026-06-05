"""Database connection and session factory management."""

import os
import logging
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from config.settings import config
from database.models import Base

logger = logging.getLogger("DATABASE")
DB_PATH = config.DB_PATH


def get_engine():
    """Create engine with WAL mode enabled."""
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


def get_db_session():
    """Get a new database session."""
    return SessionLocal()


def get_db_session_factory():
    """Return the SessionLocal factory for per-task session creation."""
    return SessionLocal


def close_db_session(session):
    """Close database session."""
    session.close()
