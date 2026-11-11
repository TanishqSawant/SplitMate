"""Shared test fixtures for SplitMate backend tests.

Uses an in-memory SQLite database so tests run without PostgreSQL.
Some PostgreSQL-specific features (UUID columns) are handled by
mapping UUID to String for SQLite compatibility.
"""

import io
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text as sa_text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.session import Base, get_db
from app.main import app
from app.models.models import User

# ---------------------------------------------------------------------------
# Test secrets & configuration
# ---------------------------------------------------------------------------
TEST_INTERNAL_SERVICE_SECRET = "test-internal-service-secret"
settings.INTERNAL_SERVICE_SECRET = TEST_INTERNAL_SERVICE_SECRET
settings.JWT_SECRET_KEY = "test-jwt-secret-key-that-is-at-least-32-bytes-long!"

# ---------------------------------------------------------------------------
# Minimal valid magic-byte prefixes for content-validation tests
# ---------------------------------------------------------------------------
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 100   # JPEG SOI + APP0 marker
VALID_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100   # PNG signature
VALID_WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100  # WEBP RIFF container
VALID_PDF_BYTES = b"%PDF-1.4\n" + b"\x00" * 100           # PDF header

# Default test user credentials
DEFAULT_TEST_USER_EMAIL = "primary_user@example.com"
DEFAULT_TEST_USER_NAME = "Primary User"
DEFAULT_TEST_USER_PASSWORD = "Password123!"

# Use an absolute path for the SQLite test DB so it works regardless of CWD.
# Each test session creates a fresh file and drops it in teardown.
_TEST_DB_PATH = Path(__file__).parent / "test.db"
SQLALCHEMY_TEST_URL = f"sqlite:///{_TEST_DB_PATH.as_posix()}"

# Remove any stale test DB from a previous aborted run before the engine is created.
for _stale in (_TEST_DB_PATH, _TEST_DB_PATH.with_suffix(".db-wal"), _TEST_DB_PATH.with_suffix(".db-shm")):
    _stale.unlink(missing_ok=True)

engine = create_engine(
    SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False}
)

# Enable foreign keys for SQLite (do NOT use WAL mode — it causes cross-connection locking in tests)
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=DELETE")  # default journal, avoids WAL lock issues
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database for each test, seeded with a primary test user.

    Deletes and recreates the database file for each test to guarantee isolation
    even after aborted test runs. This avoids SQLite WAL locking and FK-ordering
    issues with drop_all.
    """
    # Dispose all connections so the file can be deleted
    engine.dispose()
    # Delete the DB file (and any WAL/SHM artifacts) to start completely fresh
    for _f in (_TEST_DB_PATH, _TEST_DB_PATH.with_suffix(".db-wal"), _TEST_DB_PATH.with_suffix(".db-shm")):
        _f.unlink(missing_ok=True)
    # Recreate schema
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()

    def _override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    try:
        # Seed default authenticated user
        default_user = User(
            name=DEFAULT_TEST_USER_NAME,
            email=DEFAULT_TEST_USER_EMAIL,
            password_hash=hash_password(DEFAULT_TEST_USER_PASSWORD),
        )
        session.add(default_user)
        session.commit()
        session.refresh(default_user)
        yield session
    finally:
        session.close()
        app.dependency_overrides.clear()
        engine.dispose()
        for _f in (_TEST_DB_PATH, _TEST_DB_PATH.with_suffix(".db-wal"), _TEST_DB_PATH.with_suffix(".db-shm")):
            _f.unlink(missing_ok=True)


@pytest.fixture(scope="function")
def default_user(db_session):
    """Return the default test user seeded in the db_session."""
    return db_session.query(User).filter_by(email=DEFAULT_TEST_USER_EMAIL).first()


@pytest.fixture(scope="function")
def client(db_session, default_user):
    """FastAPI test client authenticated as the default test user."""
    token = create_access_token({"sub": str(default_user.id), "email": default_user.email})

    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as c:
        c.auth_user = default_user
        c.auth_token = token
        yield c


@pytest.fixture(scope="function")
def unauth_client(db_session):
    """FastAPI test client with NO authentication headers."""
    with TestClient(app) as c:
        yield c


def create_user_and_client(
    db_session,
    email: str,
    name: str = "Test User",
    password: str = "Password123!",
) -> tuple[User, TestClient, str]:
    """Helper: create an additional user and return (User, authenticated TestClient, token)."""
    user = User(
        name=name,
        email=email.strip().lower(),
        password_hash=hash_password(password),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    token = create_access_token({"sub": str(user.id), "email": user.email})
    c = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    return user, c, token
