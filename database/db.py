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
