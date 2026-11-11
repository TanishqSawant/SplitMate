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
# Valid test receipt fixtures for content validation & extraction tests
# ---------------------------------------------------------------------------
_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "receipts"
_FRESHMART_PNG_PATH = _FIXTURES_DIR / "receipt_freshmart_grocery.png"
_PDF_PATH = _FIXTURES_DIR / "receipt_05_digital_invoice.pdf"


def _make_valid_jpeg() -> bytes:
    """Generate genuinely valid, decodable JPEG receipt bytes."""
    if _FRESHMART_PNG_PATH.is_file():
        img = Image.open(_FRESHMART_PNG_PATH).convert("RGB")
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
    if _FRESHMART_PNG_PATH.is_file():
        return _FRESHMART_PNG_PATH.read_bytes()
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


@pytest.fixture(autouse=True)
def isolate_paypal_mock(request):
    """Ensure mock mode is active for standard test suite to prevent external calls,
    while allowing live tests (TestPayPalLiveSandbox) to run in live mode.
    """
    from app.services.paypal import paypal_service

    is_live_test = (
        "LiveSandbox" in getattr(request.node.cls, "__name__", "")
        or "live" in request.keywords
    )
    prev = paypal_service.mock_mode
    if is_live_test:
        paypal_service.mock_mode = False
    else:
        paypal_service.mock_mode = True
    try:
        yield
    finally:
        paypal_service.mock_mode = prev

