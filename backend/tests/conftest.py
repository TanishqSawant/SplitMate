"""Shared test fixtures for SplitMate backend tests.

Uses an in-memory SQLite database so tests run without PostgreSQL.
Some PostgreSQL-specific features (UUID columns) are handled by
mapping UUID to String for SQLite compatibility.
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.session import Base, get_db
from app.main import app

# ---------------------------------------------------------------------------
# Test secret — must be non-empty so verify_ai_service_key can compare it
# ---------------------------------------------------------------------------
TEST_INTERNAL_SERVICE_SECRET = "test-internal-service-secret"
settings.INTERNAL_SERVICE_SECRET = TEST_INTERNAL_SERVICE_SECRET

# ---------------------------------------------------------------------------
# Minimal valid magic-byte prefixes for content-validation tests
# ---------------------------------------------------------------------------
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 100   # JPEG SOI + APP0 marker
VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100   # PNG signature
VALID_WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100  # WEBP RIFF container
VALID_PDF_BYTES = b"%PDF-1.4\n" + b"\x00" * 100           # PDF header


# SQLite in-memory database for testing
SQLALCHEMY_TEST_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False}
)

# Enable WAL mode and foreign keys for SQLite
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database for each test."""
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db_session):
    """FastAPI test client with database dependency override."""
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

