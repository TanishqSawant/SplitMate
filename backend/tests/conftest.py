"""Shared test fixtures for SplitMate backend tests.

Uses an in-memory SQLite database so tests run without PostgreSQL.
Some PostgreSQL-specific features (UUID columns) are handled by
mapping UUID to String for SQLite compatibility.
"""

import io
from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image
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
# Valid test receipt fixtures for content validation & extraction tests
# ---------------------------------------------------------------------------
_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "receipts"
_CLEAR_RESTAURANT_PNG_PATH = _FIXTURES_DIR / "receipt_01_clear_restaurant.png"
_PDF_PATH = _FIXTURES_DIR / "receipt_05_digital_invoice.pdf"


def _make_valid_jpeg() -> bytes:
    """Generate genuinely valid, decodable JPEG receipt bytes."""
    if _CLEAR_RESTAURANT_PNG_PATH.is_file():
        img = Image.open(_CLEAR_RESTAURANT_PNG_PATH).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    # Fallback in-memory valid JPEG
    img = Image.new("RGB", (200, 100), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_valid_png() -> bytes:
    """Load genuinely valid PNG receipt bytes."""
    if _CLEAR_RESTAURANT_PNG_PATH.is_file():
        return _CLEAR_RESTAURANT_PNG_PATH.read_bytes()
    img = Image.new("RGB", (200, 100), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_valid_pdf() -> bytes:
    """Load genuinely valid PDF receipt bytes."""
    if _PDF_PATH.is_file():
        return _PDF_PATH.read_bytes()
    return b"%PDF-1.4\n" + b"\x00" * 100


VALID_JPEG_BYTES = _make_valid_jpeg()
VALID_PNG_BYTES = _make_valid_png()
VALID_WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100  # WEBP RIFF container
VALID_PDF_BYTES = _make_valid_pdf()

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
    try:
        _stale.unlink(missing_ok=True)
    except OSError:
        pass

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


@pytest.fixture(autouse=True)
def isolate_paypal_mock(request):
    """Ensure mock mode is active for standard test suite to prevent external calls,
    while allowing live tests (TestPayPalLiveSandbox) to run in live mode.
    """
    services = []
    try:
        from app.services.paypal import paypal_service as ps1
        if ps1 and hasattr(ps1, "mock_mode"):
            services.append(ps1)
    except ImportError:
        pass

    try:
        from app.services.paypal_service import paypal_service as ps2
        if ps2 and hasattr(ps2, "mock_mode"):
            services.append(ps2)
    except ImportError:
        pass

    is_live_test = (
        "LiveSandbox" in getattr(request.node.cls, "__name__", "")
        or "live" in request.keywords
    )

    prev_modes = [(s, s.mock_mode) for s in services]
    for s in services:
        s.mock_mode = False if is_live_test else True

    try:
        yield
    finally:
        for s, prev in prev_modes:
            s.mock_mode = prev


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
