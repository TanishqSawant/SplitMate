"""SQLAlchemy engine and session factory."""

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
import sqlite3
from decimal import Decimal

# Register SQLite adapter for Decimal to ensure seamless SQLite and PostgreSQL compatibility
sqlite3.register_adapter(Decimal, lambda d: float(d))

from app.core.config import settings

engine_kwargs = {}
if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # Optimized for Neon / Managed PostgreSQL serverless connection pooling
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 10
    engine_kwargs["max_overflow"] = 20
    engine_kwargs["pool_recycle"] = 300  # Recycle idle connections before serverless proxy timeout

engine = create_engine(
    settings.DATABASE_URL,
    **engine_kwargs,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


def get_db():
    """FastAPI dependency that yields a database session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """Context manager for a database session outside of a FastAPI request lifecycle.

    Use this in background tasks or worker threads where FastAPI's dependency
    injection is unavailable. The caller owns the transaction.

    Example::

        with get_db_context() as db:
            receipt = db.get(Receipt, receipt_id)
            ...
            db.commit()
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

