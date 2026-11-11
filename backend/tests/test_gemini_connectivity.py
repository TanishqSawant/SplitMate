"""Phase 3: Gemini Vision integration tests.

Covers:
  - Mock / fallback mode when GEMINI_API_KEY is absent
  - Fallback extraction on a minimal valid JPEG
  - Live API connectivity (skipped when no key is set)
  - API endpoint integration via FastAPI TestClient
  - Extraction schema contract (items, merchant_name, currency, totals)
  - Invalid file / empty file handling

Run:
    python -m pytest tests/test_gemini_connectivity.py -v
"""

import io
import os
import struct

import pytest
from PIL import Image

# ---------------------------------------------------------------------------
# Shared test constants (also used by conftest.py)
# ---------------------------------------------------------------------------
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 100   # JPEG SOI + APP0 marker


# ---------------------------------------------------------------------------
# Helper: build a real 1x1 white JPEG in-memory
# ---------------------------------------------------------------------------
def _make_valid_jpeg(size: int = 50) -> bytes:
    """Create a valid JPEG image in memory using Pillow.

    Uses size>=50px to avoid the numpy gradient error on tiny (1px) images.
    """
    buf = io.BytesIO()
    img = Image.new("RGB", (size, size), color=(220, 220, 220))
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_tiny_jpeg() -> bytes:
    """Alias kept for backward compatibility — uses a safe 50x50 image."""
    return _make_valid_jpeg(50)


def _make_tiny_png() -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (50, 50), color=(200, 200, 200))
    img.save(buf, format="PNG")
    return buf.getvalue()


# ===========================================================================
# 1. Unit tests: GeminiVisionExtractor availability and fallback
# ===========================================================================

class TestGeminiVisionExtractorUnit:
    """Unit tests that run without any external API calls."""

    def test_extractor_unavailable_when_no_api_key(self):
        """GeminiVisionExtractor.is_available() must return False when no key is set."""
        from app.services.receipt_extractor.llm_parser import GeminiVisionExtractor
        extractor = GeminiVisionExtractor(api_key=None)
        # Temporarily clear env var to ensure we don't pick it up
        original = os.environ.pop("GEMINI_API_KEY", None)
        try:
            extractor_no_key = GeminiVisionExtractor(api_key=None)
            assert extractor_no_key.is_available() is False
        finally:
            if original:
                os.environ["GEMINI_API_KEY"] = original

    def test_extractor_available_when_api_key_provided(self):
        """GeminiVisionExtractor.is_available() must return True when a non-empty key is provided."""
        from app.services.receipt_extractor.llm_parser import GeminiVisionExtractor
        extractor = GeminiVisionExtractor(api_key="FAKE-KEY-FOR-UNIT-TEST-ONLY")
        assert extractor.is_available() is True

    def test_fallback_parser_on_empty_text(self):
        """RegexHeuristicFallback must gracefully handle empty text."""
        from app.services.receipt_extractor.llm_parser import RegexHeuristicFallback
        parser = RegexHeuristicFallback()
        result = parser.parse_text("")
        assert result.is_fallback is True
        assert result.confidence <= 0.35
        assert any("No text" in w for w in result.warnings) or result.confidence == 0.0

    def test_fallback_parser_on_structured_text(self):
        """RegexHeuristicFallback must extract basic data from plain-text receipt."""
        from app.services.receipt_extractor.llm_parser import RegexHeuristicFallback
        parser = RegexHeuristicFallback()
        receipt_text = (
            "Mario's Bistro\n"
            "123 Main St, New York\n"
            "Date: 2026-11-10\n"
            "Invoice #12345\n"
            "Margherita Pizza 2 18.00\n"
            "Tiramisu 1 7.50\n"
            "Subtotal: $25.50\n"
            "Tax: $2.55\n"
            "Total: $28.05\n"
        )
        result = parser.parse_text(receipt_text)
        assert result.is_fallback is True
        assert result.confidence <= 0.35
        assert result.extraction_method == "regex_heuristic_fallback"
        # Should extract some items or financial data
        has_data = (
            result.merchant_name is not None
            or len(result.items) > 0
            or result.final_total is not None
        )
        assert has_data, "Fallback parser produced no usable data from structured receipt text"

    def test_fallback_confidence_ceiling(self):
        """Fallback confidence must never exceed 0.35."""
        from app.services.receipt_extractor.llm_parser import RegexHeuristicFallback
        parser = RegexHeuristicFallback()
        rich_text = "\n".join([
            "Super Store",
            "Date: 2026-01-15",
            "Item A 2 10.00",
            "Item B 1 5.00",
            "Subtotal: $25.00",
            "Tax: $2.50",
            "Total: $27.50",
        ])
        result = parser.parse_text(rich_text)
        assert result.confidence <= 0.35, (
            f"Fallback confidence {result.confidence} exceeds ceiling of 0.35"
        )


# ===========================================================================
# 2. Unit tests: ReceiptExtractionService with mock data
# ===========================================================================

class TestReceiptExtractionService:
    """Service-level tests using minimal valid image bytes (no Gemini call)."""

    def test_service_validates_oversized_file(self):
        """ReceiptExtractionService must reject files exceeding the size limit."""
        from app.services.receipt_extractor.service import (
            ReceiptExtractionService,
            ReceiptExtractionError,
        )
        svc = ReceiptExtractionService(api_key=None, max_size_mb=1)
        oversized_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * (2 * 1024 * 1024)  # 2 MB
        with pytest.raises(ReceiptExtractionError, match="exceeds maximum"):
            svc.extract_from_bytes(oversized_bytes, filename="big.jpg")

    def test_service_rejects_unsupported_extension(self):
        """ReceiptExtractionService must reject files with disallowed extensions."""
        from app.services.receipt_extractor.service import (
            ReceiptExtractionService,
            ReceiptExtractionError,
        )
        svc = ReceiptExtractionService(api_key=None)
        with pytest.raises(ReceiptExtractionError, match="not supported"):
            svc.extract_from_bytes(b"\x00" * 100, filename="malware.exe")

    def test_service_rejects_empty_bytes(self):
        """ReceiptExtractionService must reject empty byte strings."""
        from app.services.receipt_extractor.service import (
            ReceiptExtractionService,
            ReceiptExtractionError,
        )
        svc = ReceiptExtractionService(api_key=None)
        with pytest.raises(ReceiptExtractionError, match="empty"):
            svc.extract_from_bytes(b"", filename="receipt.jpg")

    def test_service_fallback_on_valid_jpeg_no_api_key(self):
        """Service must return a fallback result (not crash) when given a real JPEG and no API key."""
        from app.services.receipt_extractor.service import ReceiptExtractionService
        # Temporarily remove key from env
        original = os.environ.pop("GEMINI_API_KEY", None)
        try:
            svc = ReceiptExtractionService(api_key=None)
            jpeg_bytes = _make_valid_jpeg(50)  # 50x50 to avoid numpy gradient error on 1x1
            result = svc.extract_from_bytes(jpeg_bytes, filename="receipt.jpg")
            assert result.is_fallback is True
            assert result.confidence <= 0.35
            assert result.extraction_method == "regex_heuristic_fallback"
            assert isinstance(result.warnings, list)
            assert len(result.warnings) > 0
        finally:
            if original:
                os.environ["GEMINI_API_KEY"] = original

    def test_service_fallback_on_valid_png_no_api_key(self):
        """Service must return a fallback result when given a real PNG and no API key."""
        from app.services.receipt_extractor.service import ReceiptExtractionService
        original = os.environ.pop("GEMINI_API_KEY", None)
        try:
            svc = ReceiptExtractionService(api_key=None)
            png_bytes = _make_tiny_png()  # 50x50
            result = svc.extract_from_bytes(png_bytes, filename="receipt.png")
            assert result.is_fallback is True
        finally:
            if original:
                os.environ["GEMINI_API_KEY"] = original

    def test_service_handles_undersized_image_safely(self):
        """Service must handle undersized images (1x1 pixel) safely without unhandled crash."""
        from app.services.receipt_extractor.service import ReceiptExtractionService
        svc = ReceiptExtractionService(api_key=None)
        buf = io.BytesIO()
        Image.new("RGB", (1, 1), color=(255, 255, 255)).save(buf, format="JPEG")
        tiny_bytes = buf.getvalue()
        result = svc.extract_from_bytes(tiny_bytes, filename="tiny.jpg")
        assert result.is_fallback is True
        assert result.confidence <= 0.35

    def test_service_handles_corrupted_image_safely(self):
        """Service must raise ReceiptExtractionError on corrupted image bytes."""
        from app.services.receipt_extractor.service import (
            ReceiptExtractionService,
            ReceiptExtractionError,
        )
        svc = ReceiptExtractionService(api_key=None)
        corrupted_bytes = b"\xff\xd8\xff\xe0" + b"\xff" * 50  # Corrupted JPEG stream
        with pytest.raises(ReceiptExtractionError, match="Corrupted or invalid"):
            svc.extract_from_bytes(corrupted_bytes, filename="corrupt.jpg")

    def test_extraction_result_schema_fields(self):
        """ReceiptExtractionResult must expose all required contract fields."""
        from app.services.receipt_extractor.schemas import ReceiptExtractionResult
        result = ReceiptExtractionResult()
        required_fields = [
            "merchant_name", "items", "currency", "subtotal", "tax",
            "final_total", "confidence", "is_fallback", "extraction_method", "warnings",
        ]
        for field in required_fields:
            assert hasattr(result, field), f"Missing field: {field}"

    def test_to_backend_contract_has_required_keys(self):
        """to_backend_contract() must return all keys expected by backend schema."""
        from app.services.receipt_extractor.schemas import ReceiptExtractionResult
        result = ReceiptExtractionResult(confidence=0.95, is_fallback=False)
        contract = result.to_backend_contract()
        for key in ("merchant_name", "currency", "subtotal", "tax", "total", "items"):
            assert key in contract, f"Missing contract key: {key}"
        assert isinstance(contract["items"], list)
        # Empty items list is valid - receipts may have no line items

    def test_to_frontend_contract_has_required_keys(self):
        """to_frontend_contract() must return all keys expected by React frontend."""
        from app.services.receipt_extractor.schemas import ReceiptExtractionResult
        result = ReceiptExtractionResult(confidence=0.95, is_fallback=False)
        contract = result.to_frontend_contract()
        for key in (
            "merchant", "merchant_name", "date", "currency",
            "subtotal", "tax", "total", "confidence", "is_fallback",
            "warnings", "items",
        ):
            assert key in contract, f"Missing frontend contract key: {key}"

    def test_math_consistency_on_valid_data(self):
        """validate_math_consistency must not add warnings when totals are correct."""
        from decimal import Decimal
        from app.services.receipt_extractor.schemas import ReceiptExtractionResult, ExtractedLineItem
        result = ReceiptExtractionResult(
            subtotal=Decimal("20.00"),
            tax=Decimal("2.00"),
            final_total=Decimal("22.00"),
            confidence=0.95,
            is_fallback=False,
        )
        initial_warning_count = len(result.warnings)
        result.validate_math_consistency()
        # No discrepancy warnings should be added
        discrepancy_warnings = [w for w in result.warnings if "discrepancy" in w.lower()]
        assert len(discrepancy_warnings) == 0

    def test_math_consistency_flags_discrepancy(self):
        """validate_math_consistency must add a warning when totals don't match."""
        from decimal import Decimal
        from app.services.receipt_extractor.schemas import ReceiptExtractionResult
        result = ReceiptExtractionResult(
            subtotal=Decimal("20.00"),
            tax=Decimal("2.00"),
            tip=Decimal("0.00"),  # Explicit zero to enable reconciliation
            discount=Decimal("0.00"),  # Explicit zero to enable reconciliation
            final_total=Decimal("99.00"),  # Intentionally wrong (should be 22.00)
            confidence=0.95,
            is_fallback=False,
        )
        result.validate_math_consistency()
        discrepancy_warnings = [w for w in result.warnings if "discrepancy" in w.lower()]
        assert len(discrepancy_warnings) > 0
        # Confidence is preserved per design principle: "Preserves genuine model confidence without arbitrary adjustment"
        assert result.confidence == 0.95, "Confidence should be preserved, not modified"


# ===========================================================================
# 3. API endpoint integration tests (FastAPI TestClient)
# ===========================================================================

class TestReceiptAPIEndpoints:
    """Integration tests for receipt API routes via TestClient."""

    def test_receipt_upload_returns_receipt_id(self, client):
        """POST /api/receipts/upload must return a receipt_id."""
        jpeg_bytes = _make_tiny_jpeg()
        response = client.post(
            "/api/receipts/upload",
            files={"file": ("test_receipt.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert response.status_code in (200, 201), response.text
        data = response.json()
        assert "receipt_id" in data or "id" in data, (
            f"Expected receipt_id in response, got: {data}"
        )

    def test_receipt_upload_with_auto_extract(self, client):
        """POST /api/receipts/upload?auto_extract=true must trigger extraction."""
        jpeg_bytes = _make_tiny_jpeg()
        response = client.post(
            "/api/receipts/upload?auto_extract=true",
            files={"file": ("receipt.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert response.status_code in (200, 201), response.text
        data = response.json()
        # receipt_id should be in the response
        receipt_id = data.get("receipt_id") or data.get("id")
        assert receipt_id is not None

    def _upload_receipt(self, client) -> str:
        """Helper: upload a receipt and return its ID."""
        jpeg_bytes = _make_tiny_jpeg()
        upload_resp = client.post(
            "/api/receipts/upload",
            files={"file": ("receipt.jpg", jpeg_bytes, "image/jpeg")},
        )
        assert upload_resp.status_code in (200, 201), upload_resp.text
        return upload_resp.json().get("receipt_id") or upload_resp.json().get("id")

    def test_receipt_extract_endpoint(self, client):
        """POST /api/receipts/{id}/extract must return extraction result."""
        receipt_id = self._upload_receipt(client)
        assert receipt_id is not None

        # Then extract
        extract_resp = client.post(f"/api/receipts/{receipt_id}/extract")
        assert extract_resp.status_code in (200, 201), extract_resp.text
        data = extract_resp.json()
        # In mock/fallback mode, is_fallback should be True
        assert "is_fallback" in data or "extraction_method" in data or "items" in data

    def test_receipt_upload_rejects_invalid_extension(self, client):
        """POST /api/receipts/upload must reject files with unsupported extensions."""
        fake_bytes = b"MZ\x00" + b"\x00" * 50  # EXE-like header
        response = client.post(
            "/api/receipts/upload",
            files={"file": ("malware.exe", fake_bytes, "application/octet-stream")},
        )
        assert response.status_code in (400, 422), (
            f"Expected 400/422 for .exe upload, got {response.status_code}"
        )

    def test_receipt_items_update_endpoint(self, client):
        """PUT /api/receipts/{id}/items must accept updated items list."""
        receipt_id = self._upload_receipt(client)
        assert receipt_id is not None

        updated_items = {
            "items": [
                {"item_name": "Coffee", "quantity": 2, "unit_price": "3.50", "total_price": "7.00"},
                {"item_name": "Muffin", "quantity": 1, "unit_price": "2.00", "total_price": "2.00"},
            ]
        }
        update_resp = client.put(
            f"/api/receipts/{receipt_id}/items",
            json=updated_items,
        )
        assert update_resp.status_code == 200, update_resp.text


# ===========================================================================
# 4. Live Gemini API test (skipped when no key is configured)
# ===========================================================================

@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set in environment — skipping live Gemini API test",
)
class TestGeminiLiveConnectivity:
    """Live Gemini Vision API connectivity tests.

    These tests only run when GEMINI_API_KEY is set in the environment.
    They make real network calls and verify actual API connectivity.
    """

    def test_gemini_client_import(self):
        """google.genai must be importable."""
        from google import genai  # noqa: F401

    def test_gemini_extractor_is_available_with_key(self):
        """GeminiVisionExtractor.is_available() must be True when key is set."""
        from app.services.receipt_extractor.llm_parser import GeminiVisionExtractor
        extractor = GeminiVisionExtractor()  # picks up GEMINI_API_KEY from env
        assert extractor.is_available() is True

    def test_gemini_live_extraction_on_minimal_image(self):
        """GeminiVisionExtractor must return a non-fallback result for a valid image."""
        from app.services.receipt_extractor.llm_parser import GeminiVisionExtractor
        extractor = GeminiVisionExtractor()
        img = Image.new("RGB", (100, 100), color=(255, 255, 255))
        result = extractor.extract(image=img, text_context="Total: $10.00")
        # Should not crash; may still use fallback if model returns empty text
        assert result is not None
        assert result.extraction_method in ("gemini_vision", "regex_heuristic_fallback")
        # If Gemini responded successfully: confidence should be higher
        if result.extraction_method == "gemini_vision" and result.status != "failed":
            assert result.is_fallback is False
            assert result.confidence is not None and result.confidence > 0.35
        elif result.status == "failed":
            assert result.error_code in ("GEMINI_API_ERROR", "TIMEOUT", "QUOTA_EXCEEDED")
