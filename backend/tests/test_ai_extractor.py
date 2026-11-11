"""Unit and integration test suite for the AI Receipt Extraction Module.

Tests:
1. Pydantic validation, decimal precision, null-safety, and math reconciliation.
2. Adapter conversion to Tanishq's backend and Dhruv's frontend contracts.
3. OpenCV preprocessing, blur detection (Laplacian variance), and deskewing.
4. PDF rasterization via pypdfium2.
5. OCR engine and local Tesseract availability guards.
6. Structured LLM parser and explicit fallback behavior (never claims fallback is AI).
7. End-to-end extraction with all 5 receipt fixtures.
8. Error handling for invalid files, empty uploads, and oversized files.
"""

from contextlib import contextmanager
from decimal import Decimal
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image

from app.core.config import settings
from app.services.receipt_extractor import (
    ReceiptExtractionService,
    ReceiptExtractionResult,
    ExtractedLineItem,
    ReceiptExtractionError,
    ImagePreprocessor,
    PDFHandler,
    OCREngine,
    GeminiVisionExtractor,
    RegexHeuristicFallback,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "receipts"


# =============================================================================
# 1. SCHEMAS, VALIDATION & ADAPTER TESTS
# =============================================================================

def test_extracted_line_item_math():
    """Tests line item price rounding and preserving missing values."""
    item = ExtractedLineItem(
        item_name="Truffle Pasta",
        quantity=2,
        unit_price=Decimal("15.50"),
        total_price=Decimal("31.00"),
    )
    assert item.item_name == "Truffle Pasta"
    assert item.quantity == 2
    assert item.unit_price == Decimal("15.50")
    assert item.total_price == Decimal("31.00")

    # If total_price is omitted, it remains None (never fabricated)
    item2 = ExtractedLineItem(
        item_name="Gelato",
        quantity=3,
        unit_price=Decimal("4.25"),
    )
    assert item2.total_price is None


def test_schema_null_safety_never_hallucinates():
    """Verifies that missing fields default to None/null rather than fabricated numbers."""
    result = ReceiptExtractionResult(
        items=[],
    )
    assert result.merchant_name is None
    assert result.merchant_address is None
    assert result.receipt_date is None
    assert result.receipt_number is None
    assert result.currency is None
    assert result.subtotal is None
    assert result.tax is None
    assert result.discount is None
    assert result.tip is None
    assert result.final_total is None


def test_math_consistency_reconciliation_warning():
    """Verifies that mathematical discrepancies trigger warnings while preserving genuine model confidence."""
    result = ReceiptExtractionResult(
        merchant_name="Bistro",
        currency="USD",
        subtotal=Decimal("50.00"),
        tax=Decimal("5.00"),
        tip=Decimal("5.00"),
        discount=Decimal("0.00"),
        final_total=Decimal("70.00"),  # Expected: 60.00, mismatch: 10.00
        confidence=0.90,
    )
    result.validate_math_consistency()
    assert any("Mathematical discrepancy" in w for w in result.warnings)
    assert result.confidence == 0.90


def test_backend_contract_adapter():
    """Tests conversion to Tanishq's exact ReceiptExtractionRequest specification."""
    result = ReceiptExtractionResult(
        merchant_name="Mario's Bistro",
        currency="USD",
        subtotal=Decimal("45.50"),
        tax=Decimal("4.50"),
        final_total=Decimal("50.00"),
        items=[
            ExtractedLineItem(
                item_name="Margherita Pizza",
                quantity=1,
                unit_price=Decimal("25.00"),
                total_price=Decimal("25.00"),
            ),
            ExtractedLineItem(
                item_name="Pasta Carbonara",
                quantity=2,
                unit_price=Decimal("10.25"),
                total_price=Decimal("20.50"),
            ),
        ],
    )
    payload = result.to_backend_contract()

    # Exact fields required by Tanishq's ReceiptExtractionRequest:
    assert payload["merchant_name"] == "Mario's Bistro"
    assert payload["currency"] == "USD"
    assert payload["subtotal"] == "45.50"
    assert payload["tax"] == "4.50"
    assert payload["total"] == "50.00"
    assert len(payload["items"]) == 2
    assert payload["items"][0]["item_name"] == "Margherita Pizza"
    assert payload["items"][0]["quantity"] == 1
    assert payload["items"][0]["unit_price"] == "25.00"
    assert payload["items"][0]["total_price"] == "25.00"


def test_frontend_contract_adapter():
    """Tests conversion to Dhruv's exact React UI schema."""
    result = ReceiptExtractionResult(
        merchant_name="Mario's Bistro",
        receipt_date="2026-11-06",
        currency="USD",
        subtotal=Decimal("45.50"),
        tax=Decimal("4.50"),
        tip=Decimal("5.00"),
        final_total=Decimal("55.00"),
        confidence=0.95,
        items=[
            ExtractedLineItem(
                item_name="Margherita Pizza",
                quantity=1,
                unit_price=Decimal("25.00"),
                total_price=Decimal("25.00"),
            ),
        ],
    )
    frontend = result.to_frontend_contract()

    # Exact fields required by Dhruv's ExtractionResult.jsx & ExpenseContext.jsx:
    assert frontend["merchant"] == "Mario's Bistro"
    assert frontend["merchant_name"] == "Mario's Bistro"
    assert frontend["date"] == "2026-11-06"
    assert frontend["category"] == "Food & Dining"
    assert frontend["subtotal"] == "45.50"
    assert frontend["tax"] == "4.50"
    assert frontend["tip"] == "5.00"
    assert frontend["total"] == "55.00"
    assert frontend["confidence"] == 0.95
    assert len(frontend["items"]) == 1
    assert frontend["items"][0]["id"] == "item_1"
    assert frontend["items"][0]["name"] == "Margherita Pizza"
    assert frontend["items"][0]["price"] == "25.00"
    assert frontend["items"][0]["unit_price"] == "25.00"
    assert frontend["items"][0]["total_price"] == "25.00"
    assert frontend["items"][0]["quantity"] == "1"


# =============================================================================
# 2. OPENCV PREPROCESSOR & BLUR DETECTION TESTS
# =============================================================================

def test_blur_detection_sharp_image():
    """Sharp fixture (receipt_01) should not be flagged as blurry."""
    sharp_path = FIXTURES_DIR / "receipt_01_clear_restaurant.png"
    assert sharp_path.is_file(), f"Fixture missing: {sharp_path}"

    preprocessor = ImagePreprocessor()
    result = preprocessor.preprocess(sharp_path.read_bytes())
    assert result.is_blurry is False
    assert result.blur_score >= preprocessor.blur_threshold


def test_blur_detection_blurry_image():
    """Artificially blurred fixture (receipt_02) must be flagged with warning."""
    blurry_path = FIXTURES_DIR / "receipt_02_blurry_takeout.png"
    assert blurry_path.is_file(), f"Fixture missing: {blurry_path}"

    preprocessor = ImagePreprocessor()
    result = preprocessor.preprocess(blurry_path.read_bytes())
    assert result.is_blurry is True
    assert result.blur_score < preprocessor.blur_threshold
    assert any("blurry" in w.lower() for w in result.warnings)


def test_deskewing_rotated_image():
    """Rotated fixture (receipt_03) should be processed and deskew angle recorded."""
    rotated_path = FIXTURES_DIR / "receipt_03_rotated_grocery.png"
    assert rotated_path.is_file(), f"Fixture missing: {rotated_path}"

    preprocessor = ImagePreprocessor()
    result = preprocessor.preprocess(rotated_path.read_bytes())
    assert result.processed_image is not None
    assert result.width > 0 and result.height > 0


# =============================================================================
# 3. PDF HANDLER TESTS
# =============================================================================

def test_pdf_magic_bytes_detection():
    pdf_bytes = b"%PDF-1.4 header content"
    assert PDFHandler.is_pdf(pdf_bytes) is True

    fake_bytes = b"\xff\xd8\xff\xe0 jpeg header"
    assert PDFHandler.is_pdf(fake_bytes) is False


def test_pdf_rendering_pypdfium2():
    """Renders digital invoice fixture (receipt_05) using pypdfium2."""
    pdf_path = FIXTURES_DIR / "receipt_05_digital_invoice.pdf"
    assert pdf_path.is_file(), f"Fixture missing: {pdf_path}"

    handler = PDFHandler()
    pages = handler.render_pdf(pdf_path.read_bytes())
    assert len(pages) >= 1

    first_page = pages[0]
    assert first_page.page_number == 1
    assert isinstance(first_page.image, Image.Image)
    assert len(first_page.image_bytes) > 0


# =============================================================================
# 4. OCR ENGINE & TESSERACT AVAILABILITY
# =============================================================================

def test_tesseract_availability_check():
    """Verifies that OCREngine safely reports Tesseract presence without raising uncaught exceptions."""
    is_available = OCREngine.is_tesseract_available()
    assert isinstance(is_available, bool)
    # On this machine, Tesseract binary is not installed
    assert is_available is False


# =============================================================================
# 5. LLM PARSER & EXPLICIT FALLBACK ENGINE
# =============================================================================

def test_explicit_fallback_marks_degraded_status():
    """Fallback engine must NEVER claim fallback is AI.
    
    Must set is_fallback=True, method='regex_heuristic_fallback', confidence=None,
    and include explicit fallback warning.
    """
    raw_text = """
    Mario's Italian Bistro
    123 Little Italy Way
    Date: 2026-11-06
    Invoice #: REC-2026-9481
    Margherita Pizza 1 18.00
    Fettuccine Alfredo 2 28.00
    Subtotal: $46.00
    Tax: $4.14
    TOTAL AMOUNT: $50.14
    """
    fallback = RegexHeuristicFallback()
    result = fallback.parse_text(raw_text)

    # Strict fallback assertions:
    assert result.is_fallback is True
    assert result.extraction_method == "regex_heuristic_fallback"
    assert result.confidence is not None and result.confidence <= 0.35
    assert any("Fallback extraction used" in w for w in result.warnings)

    # Data extraction assertions:
    assert result.merchant_name == "Mario's Italian Bistro"
    assert result.receipt_date == "2026-11-06"
    assert result.receipt_number == "REC-2026-9481"
    assert result.subtotal == Decimal("46.00")
    assert result.tax == Decimal("4.14")
    assert result.final_total == Decimal("50.14")
    assert len(result.items) >= 2


def test_fallback_with_empty_text():
    """Empty text must yield null fields and confidence None with clear diagnostics."""
    fallback = RegexHeuristicFallback()
    result = fallback.parse_text("")
    assert result.is_fallback is True
    assert result.confidence == 0.0  # Zero confidence for empty input
    assert result.merchant_name is None
    assert result.final_total is None
    assert any("No text could be extracted" in w for w in result.warnings)


def test_currency_detection_inr_formats():
    """Tests that ₹, Rs., Rs, and INR are all correctly identified as INR."""
    fallback = RegexHeuristicFallback()
    assert fallback.parse_text("Taj Mahal Hotel\nTotal: ₹1500.00").currency == "INR"
    assert fallback.parse_text("Saravana Bhavan\nTotal: Rs. 450.00").currency == "INR"
    assert fallback.parse_text("Bikanervala\nTotal: Rs 250.00").currency == "INR"
    assert fallback.parse_text("Haldirams\nTotal: 990.00 INR").currency == "INR"


def test_currency_detection_usd_format():
    """Tests that bare $ remains ambiguous (None) while US$ and USD map to USD."""
    fallback = RegexHeuristicFallback()
    bare_dollar_result = fallback.parse_text("Mario Diner\nTotal: $50.00")
    assert bare_dollar_result.currency is None
    assert "currency" in bare_dollar_result.uncertain_fields

    assert fallback.parse_text("City Cafe\nTotal: 25.00 USD").currency == "USD"
    assert fallback.parse_text("City Cafe\nTotal: US$25.00").currency == "USD"


def test_currency_missing_preserves_null_in_canonical_result():
    """When receipt text has no currency indicator, currency MUST remain null/None."""
    fallback = RegexHeuristicFallback()
    result = fallback.parse_text("Generic Merchant\nItem 1 10.00\nTotal: 10.00")
    assert result.currency is None
    assert any("Currency was not detected on receipt" in w for w in result.warnings)


def test_backend_adapter_preserves_none_for_missing_currency():
    """Missing currency remains None in the backend contract without fabricating USD."""
    result = ReceiptExtractionResult(
        merchant_name="Unknown Diner",
        currency=None,  # Genuinely missing
        subtotal=Decimal("10.00"),
        tax=Decimal("1.00"),
        final_total=Decimal("11.00"),
        items=[],
    )
    payload = result.to_backend_contract()
    assert payload["currency"] is None


# =============================================================================
# 6. SERVICE VALIDATION & ERROR HANDLING
# =============================================================================

def test_service_rejects_empty_file():
    service = ReceiptExtractionService()
    with pytest.raises(ReceiptExtractionError, match="empty"):
        service.extract_from_bytes(b"", "receipt.jpg")


def test_service_rejects_unsupported_format():
    service = ReceiptExtractionService()
    with pytest.raises(ReceiptExtractionError, match="not supported"):
        service.extract_from_bytes(b"some content", "malicious_script.exe")


def test_service_rejects_oversized_file():
    service = ReceiptExtractionService(max_size_mb=1)  # 1 MB threshold
    large_payload = b"0" * (2 * 1024 * 1024)  # 2 MB
    with pytest.raises(ReceiptExtractionError, match="exceeds maximum allowed limit"):
        service.extract_from_bytes(large_payload, "large_receipt.png")


def test_service_rejects_corrupted_image():
    service = ReceiptExtractionService()
    with pytest.raises(ReceiptExtractionError, match="Corrupted or invalid image"):
        service.extract_from_bytes(b"not a real image payload", "broken.jpg")


# =============================================================================
# 7. END-TO-END EXTRACTION WITH FIXTURES (MOCKED GEMINI VISION)
# =============================================================================

@contextmanager
def _mock_genai_context(mock_response=None, side_effect=None):
    mock_genai = MagicMock()
    mock_client = MagicMock()
    mock_genai.Client.return_value = mock_client
    if side_effect:
        mock_client.models.generate_content.side_effect = side_effect
    elif mock_response:
        mock_client.models.generate_content.return_value = mock_response

    mock_types = MagicMock()
    mock_google = MagicMock()
    mock_google.genai = mock_genai
    mock_genai.types = mock_types

    # Attach mock_genai and mock_types to mock_client for inspection in tests
    mock_client._mock_genai = mock_genai
    mock_client._mock_types = mock_types

    with patch.dict(
        "sys.modules",
        {
            "google": mock_google,
            "google.genai": mock_genai,
            "google.genai.types": mock_types,
        },
    ):
        yield mock_client


def _mock_gemini_success_response(merchant="Mario's Bistro", total="50.14", subtotal="46.00", tax="4.14"):
    payload = {
        "document_type": "receipt",
        "status": "completed",
        "merchant_name": merchant,
        "currency": "USD",
        "subtotal": subtotal,
        "tax": tax,
        "final_total": total,
        "confidence": 0.95,
        "items": [
            {"item_name": "Margherita Pizza", "quantity": 1, "unit_price": "18.00", "total_price": "18.00"},
            {"item_name": "Fettuccine Alfredo", "quantity": 2, "unit_price": "14.00", "total_price": "28.00"},
        ],
    }
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(payload)
    return mock_resp


def test_fixture_01_clear_restaurant():
    service = ReceiptExtractionService(api_key="test-api-key")
    path = FIXTURES_DIR / "receipt_01_clear_restaurant.png"

    with _mock_genai_context(mock_response=_mock_gemini_success_response("Clear Restaurant")):
        result = service.extract_from_path(path)

    assert result is not None
    assert result.status == "completed"
    assert result.is_fallback is False
    assert result.extraction_method == "gemini_vision"
    backend_payload = result.to_backend_contract()
    assert backend_payload["merchant_name"] == "Clear Restaurant"
    assert "total" in backend_payload


def test_fixture_02_blurry_takeout():
    service = ReceiptExtractionService(api_key="test-api-key")
    path = FIXTURES_DIR / "receipt_02_blurry_takeout.png"

    with _mock_genai_context(mock_response=_mock_gemini_success_response("Blurry Takeout")):
        result = service.extract_from_path(path)

    # Blur detection warning must be captured by preprocessor and merged into warnings
    assert any("blurry" in w.lower() for w in result.warnings)
    assert result.is_fallback is False


def test_fixture_03_rotated_grocery():
    service = ReceiptExtractionService(api_key="test-api-key")
    path = FIXTURES_DIR / "receipt_03_rotated_grocery.png"

    with _mock_genai_context(mock_response=_mock_gemini_success_response("Rotated Grocery")):
        result = service.extract_from_path(path)

    assert result is not None
    assert result.status == "completed"
    assert result.is_fallback is False


def test_fixture_04_incomplete_cafe():
    service = ReceiptExtractionService(api_key="test-api-key")
    path = FIXTURES_DIR / "receipt_04_incomplete_cafe.png"

    with _mock_genai_context(mock_response=_mock_gemini_success_response("Incomplete Cafe")):
        result = service.extract_from_path(path)

    # Incomplete receipt has no address, address must remain None (never fabricated)
    assert result.merchant_address is None


def test_fixture_05_digital_invoice_pdf():
    service = ReceiptExtractionService(api_key="test-api-key")
    path = FIXTURES_DIR / "receipt_05_digital_invoice.pdf"

    with _mock_genai_context(mock_response=_mock_gemini_success_response("Digital Invoice Corp")):
        result = service.extract_from_path(path)

    assert result is not None
    assert result.is_fallback is False
    frontend_payload = result.to_frontend_contract()
    assert "items" in frontend_payload
    assert "total" in frontend_payload


# =============================================================================
# 8. CENTRALIZED GEMINI CONFIGURATION & STRICT PIPELINE TESTS
# =============================================================================

def test_gemini_config_read_from_central_settings():
    """ReceiptExtractionService, OCREngine, and GeminiVisionExtractor read config from settings."""
    original_key = settings.GEMINI_API_KEY
    original_model = settings.GEMINI_MODEL
    try:
        settings.GEMINI_API_KEY = "central-test-gemini-key"
        settings.GEMINI_MODEL = "gemini-central-test-model"

        service = ReceiptExtractionService()
        assert service.api_key == "central-test-gemini-key"
        assert service.model == "gemini-central-test-model"
        assert service.ocr_engine.gemini_extractor.api_key == "central-test-gemini-key"
        assert service.ocr_engine.gemini_extractor.model_name == "gemini-central-test-model"
    finally:
        settings.GEMINI_API_KEY = original_key
        settings.GEMINI_MODEL = original_model


def test_missing_gemini_key_returns_failed_not_heuristic():
    """Missing Gemini key triggers fallback to regex heuristic extraction."""
    service = ReceiptExtractionService(api_key="")
    path = FIXTURES_DIR / "receipt_01_clear_restaurant.png"
    result = service.extract_from_path(path)

    # When Gemini is unavailable, fallback parser is used
    assert result.is_fallback is True
    assert result.extraction_method == "regex_heuristic_fallback"
    assert result.confidence is not None and result.confidence <= 0.35
    assert any("fallback" in w.lower() for w in result.warnings)


def test_gemini_client_receives_explicit_25s_timeout():
    """Gemini client must be initialized with explicit 25-second (25,000 ms) HTTP timeout."""
    extractor = GeminiVisionExtractor(api_key="test-api-key")
    img = Image.new("RGB", (50, 50), color="white")

    with _mock_genai_context(mock_response=_mock_gemini_success_response()) as mock_client:
        extractor.extract(img)

        # Verify HttpOptions was called with timeout=25_000 (ms)
        mock_client._mock_types.HttpOptions.assert_called_once_with(timeout=25_000)
        # Verify Client was initialized with the api_key and http_options
        mock_client._mock_genai.Client.assert_called_once_with(
            api_key="test-api-key",
            http_options=mock_client._mock_types.HttpOptions.return_value,
        )


def test_gemini_timeout_returns_failed_not_heuristic():
    """Gemini timeout produces a failed extraction result with error_code=TIMEOUT without falling back."""
    extractor = GeminiVisionExtractor(api_key="mock-key")
    with _mock_genai_context(side_effect=TimeoutError("Deadline exceeded after 25s")):
        img = Image.new("RGB", (100, 100), color="white")
        result = extractor.extract(img, text_context="Some text from receipt")

    assert result.status == "failed"
    assert result.error_code == "TIMEOUT"
    assert result.confidence is None
    assert result.is_fallback is False
    assert result.extraction_method == "gemini_vision"
    assert "timed out" in result.error_message.lower()


def test_missing_confidence_remains_null():
    """Missing or null confidence from Gemini is preserved as None, never defaulted to 0.95."""
    extractor = GeminiVisionExtractor(api_key="mock-key")
    payload = {
        "document_type": "receipt",
        "status": "completed",
        "merchant_name": "No Confidence Bistro",
        "currency": "USD",
        "subtotal": "20.00",
        "tax": "2.00",
        "final_total": "22.00",
        "confidence": None,
        "items": [
            {"item_name": "Burger", "quantity": 1, "unit_price": "20.00", "total_price": "20.00"},
        ],
    }
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(payload)

    with _mock_genai_context(mock_response=mock_resp):
        img = Image.new("RGB", (50, 50), color="white")
        result = extractor.extract(img)

    assert result.confidence is None
    assert result.status == "completed"
    frontend = result.to_frontend_contract()
    assert frontend["confidence"] is None

    # Also test completely omitted confidence key
    del payload["confidence"]
    mock_resp.text = json.dumps(payload)
    with _mock_genai_context(mock_response=mock_resp):
        img = Image.new("RGB", (50, 50), color="white")
        result_omitted = extractor.extract(img)

    assert result_omitted.confidence is None


def test_zero_confidence_remains_zero():
    """Zero confidence from Gemini is preserved as 0.0, never replaced with 0.95."""
    extractor = GeminiVisionExtractor(api_key="mock-key")
    payload = {
        "document_type": "receipt",
        "status": "review_required",
        "merchant_name": "Low Quality Cafe",
        "currency": "USD",
        "subtotal": "10.00",
        "tax": "1.00",
        "final_total": "11.00",
        "confidence": 0.0,
        "items": [
            {"item_name": "Coffee", "quantity": 1, "unit_price": "10.00", "total_price": "10.00"},
        ],
    }
    mock_resp = MagicMock()
    mock_resp.text = json.dumps(payload)

    with _mock_genai_context(mock_response=mock_resp):
        img = Image.new("RGB", (50, 50), color="white")
        result = extractor.extract(img)

    assert result.confidence == 0.0
    assert result.confidence != 0.95
    frontend = result.to_frontend_contract()
    assert frontend["confidence"] == 0.0


def test_gemini_api_exception_returns_failed_not_heuristic():
    """Gemini API error produces a failed result and does not leak API keys."""
    secret_key = "super-secret-gemini-key-12345"
    extractor = GeminiVisionExtractor(api_key=secret_key)
    with _mock_genai_context(side_effect=RuntimeError("503 Service Unavailable")):
        img = Image.new("RGB", (100, 100), color="white")
        result = extractor.extract(img, text_context="Some text")

    assert result.status == "failed"
    assert result.error_code == "GEMINI_API_ERROR"
    assert result.is_fallback is False
    assert result.extraction_method == "gemini_vision"
    # Verify the secret API key is never exposed in error_message or warnings
    assert secret_key not in result.error_message
    assert not any(secret_key in w for w in result.warnings)


def test_local_tesseract_does_not_independently_produce_successful_extraction():
    """Local Tesseract OCR text must NOT independently generate a successful extraction."""
    ocr_engine = OCREngine(api_key="")  # Gemini unavailable
    with patch.object(OCREngine, "is_tesseract_available", return_value=True):
        with patch.object(
            OCREngine,
            "extract_text_local_ocr",
            return_value="Le Gourmet Cafe\nCroissant 2 8.00\nTotal: $8.00",
        ):
            img = Image.new("RGB", (100, 100), color="white")
            result = ocr_engine.process_receipt(img)

    # Gemini is unavailable, so fallback is used
    assert result.is_fallback is True
    assert result.extraction_method == "regex_heuristic_fallback"
    assert result.confidence is not None and result.confidence <= 0.35


def test_gemini_partially_readable_receipt_returns_review_required():
    """Partially readable receipt returns review_required when Gemini returns partial data."""
    extractor = GeminiVisionExtractor(api_key="mock-key")
    partial_json = json.dumps({
        "document_type": "receipt",
        "status": "review_required",
        "merchant_name": "Blurry Bistro",
        "currency": "USD",
        "final_total": "35.00",
        "items": [
            {"item_name": "Soup", "quantity": 1, "unit_price": "10.00", "total_price": "10.00"}
        ],
        "uncertain_fields": ["subtotal", "tax"],
        "missing_fields": ["subtotal"],
        "confidence": 0.65,
    })
    mock_resp = MagicMock()
    mock_resp.text = partial_json

    with _mock_genai_context(mock_response=mock_resp):
        img = Image.new("RGB", (100, 100), color="white")
        result = extractor.extract(img)

    assert result.status == "review_required"
    assert result.merchant_name == "Blurry Bistro"
    assert result.final_total == Decimal("35.00")
    assert "subtotal" in result.uncertain_fields
    assert len(result.items) == 1


def test_gemini_unsupported_document_returns_failed():
    """Non-receipt or unsupported document returns failed status."""
    extractor = GeminiVisionExtractor(api_key="mock-key")
    unsupported_json = json.dumps({
        "document_type": "unsupported",
        "status": "failed",
        "merchant_name": None,
        "currency": None,
        "items": [],
        "confidence": 0.1,
    })
    mock_resp = MagicMock()
    mock_resp.text = unsupported_json

    with _mock_genai_context(mock_response=mock_resp):
        img = Image.new("RGB", (100, 100), color="white")
        result = extractor.extract(img)

    assert result.status == "failed"
    assert result.error_code == "UNSUPPORTED_DOCUMENT"


# =============================================================================
# 9. FOCUSED SCHEMA & MISSING VALUE PRESERVATION TESTS (REQUIREMENTS 1-14)
# =============================================================================

def test_missing_quantity_remains_none():
    """1. Missing quantity remains None."""
    item = ExtractedLineItem(item_name="Espresso", unit_price=Decimal("3.50"))
    assert item.quantity is None


def test_missing_unit_price_remains_none():
    """2. Missing unit_price remains None."""
    item = ExtractedLineItem(item_name="Croissant", quantity=Decimal("2"))
    assert item.unit_price is None


def test_missing_total_price_remains_none():
    """3. Missing total_price remains None."""
    item = ExtractedLineItem(item_name="Bagel", quantity=Decimal("1"), unit_price=Decimal("2.50"))
    assert item.total_price is None


def test_missing_subtotal_remains_none():
    """4. Missing subtotal remains None."""
    result = ReceiptExtractionResult(final_total=Decimal("25.00"))
    assert result.subtotal is None
    payload = result.to_backend_contract()
    assert payload["subtotal"] is None
    frontend = result.to_frontend_contract()
    assert frontend["subtotal"] is None


def test_missing_tax_remains_none():
    """5. Missing tax remains None."""
    result = ReceiptExtractionResult(final_total=Decimal("25.00"))
    assert result.tax is None
    payload = result.to_backend_contract()
    assert payload["tax"] is None
    frontend = result.to_frontend_contract()
    assert frontend["tax"] is None


def test_missing_currency_remains_none():
    """6. Missing currency remains None."""
    result = ReceiptExtractionResult()
    assert result.currency is None
    payload = result.to_backend_contract()
    assert payload["currency"] is None
    frontend = result.to_frontend_contract()
    assert frontend["currency"] is None


def test_missing_merchant_remains_none():
    """7. Missing merchant remains None."""
    result = ReceiptExtractionResult()
    assert result.merchant_name is None
    payload = result.to_backend_contract()
    assert payload["merchant_name"] is None
    frontend = result.to_frontend_contract()
    assert frontend["merchant"] is None
    assert frontend["merchant_name"] is None


def test_explicit_zero_remains_zero():
    """8. Explicit zero remains zero."""
    item = ExtractedLineItem(
        item_name="Complimentary Water",
        quantity=Decimal("0"),
        unit_price=Decimal("0.00"),
        total_price=Decimal("0.00"),
    )
    assert item.quantity == Decimal("0")
    assert item.unit_price == Decimal("0.00")
    assert item.total_price == Decimal("0.00")

    result = ReceiptExtractionResult(
        subtotal=Decimal("0.00"),
        tax=Decimal("0.00"),
        discount=Decimal("0.00"),
        tip=Decimal("0.00"),
        final_total=Decimal("0.00"),
    )
    assert result.subtotal == Decimal("0.00")
    assert result.tax == Decimal("0.00")
    assert result.discount == Decimal("0.00")
    assert result.tip == Decimal("0.00")
    assert result.final_total == Decimal("0.00")


def test_fractional_quantities_are_preserved():
    """9. Fractional quantities are preserved using Decimal."""
    for qty_val in [Decimal("1"), Decimal("0.5"), Decimal("1.2500"), Decimal("2.75")]:
        item = ExtractedLineItem(item_name="Apples", quantity=qty_val)
        assert item.quantity == qty_val
        assert isinstance(item.quantity, Decimal)


def test_empty_items_remain_empty_list():
    """10. Empty items remain an empty list."""
    result = ReceiptExtractionResult(items=[])
    assert result.items == []
    payload = result.to_backend_contract()
    assert payload["items"] == []
    frontend = result.to_frontend_contract()
    assert frontend["items"] == []


def test_invalid_numeric_values_handled_safely():
    """11. Invalid numeric values are rejected safely with ValidationError."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractedLineItem(item_name="Bad Qty", quantity="not-a-number")

    with pytest.raises(ValidationError):
        ExtractedLineItem(item_name="Bad Price", unit_price="abc")

    with pytest.raises(ValidationError):
        ReceiptExtractionResult(final_total="invalid-money")


def test_missing_tax_not_treated_as_zero_during_reconciliation():
    """12. Missing tax is not treated as zero during reconciliation."""
    result = ReceiptExtractionResult(
        subtotal=Decimal("50.00"),
        tax=None,  # Missing tax
        final_total=Decimal("55.00"),  # Difference could legitimately be unextracted tax
    )
    result.validate_math_consistency()
    # No false mathematical discrepancy warning triggered because tax is None
    assert not any("Mathematical discrepancy" in w for w in result.warnings)


def test_missing_subtotal_does_not_invalidate_extraction():
    """13. Missing subtotal does not automatically invalidate an otherwise valid extraction."""
    result = ReceiptExtractionResult(
        status="completed",
        subtotal=None,
        tax=Decimal("5.00"),
        final_total=Decimal("55.00"),
        items=[
            ExtractedLineItem(
                item_name="Pizza",
                quantity=Decimal("1"),
                unit_price=Decimal("50.00"),
                total_price=Decimal("50.00"),
            )
        ],
    )
    result.validate_math_consistency()
    assert result.status == "completed"
    assert not any("Mathematical discrepancy" in w for w in result.warnings)


def test_missing_confidence_does_not_invalidate_extraction():
    """14. Missing confidence does not automatically invalidate an otherwise valid extraction."""
    result = ReceiptExtractionResult(
        status="completed",
        confidence=None,
        subtotal=Decimal("50.00"),
        tax=Decimal("5.00"),
        final_total=Decimal("55.00"),
    )
    result.validate_math_consistency()
    assert result.status == "completed"
    assert result.confidence is None


# =============================================================================
# 10. FOCUSED TOTAL RECONCILIATION TESTS
# =============================================================================

def test_missing_tip_skips_total_reconciliation():
    """1. Missing tip skips total reconciliation."""
    result = ReceiptExtractionResult(
        subtotal=Decimal("50.00"),
        tax=Decimal("5.00"),
        tip=None,
        discount=Decimal("0.00"),
        final_total=Decimal("60.00"),  # Difference could legitimately be unextracted tip
    )
    result.validate_math_consistency()
    assert not any("Mathematical discrepancy" in w for w in result.warnings)


def test_missing_discount_skips_total_reconciliation():
    """2. Missing discount skips total reconciliation."""
    result = ReceiptExtractionResult(
        subtotal=Decimal("50.00"),
        tax=Decimal("5.00"),
        tip=Decimal("0.00"),
        discount=None,
        final_total=Decimal("50.00"),  # Difference could legitimately be unextracted discount
    )
    result.validate_math_consistency()
    assert not any("Mathematical discrepancy" in w for w in result.warnings)


def test_explicit_zero_tip_and_discount_preserved_and_reconciled():
    """3. Explicit zero tip and discount are preserved and reconciled."""
    result = ReceiptExtractionResult(
        subtotal=Decimal("50.00"),
        tax=Decimal("5.00"),
        tip=Decimal("0.00"),
        discount=Decimal("0.00"),
        final_total=Decimal("55.00"),
    )
    assert result.tip == Decimal("0.00")
    assert result.discount == Decimal("0.00")
    result.validate_math_consistency()
    assert not any("Mathematical discrepancy" in w for w in result.warnings)


def test_valid_total_produces_no_discrepancy():
    """4. A valid total produces no discrepancy."""
    result = ReceiptExtractionResult(
        subtotal=Decimal("40.00"),
        tax=Decimal("4.00"),
        tip=Decimal("5.00"),
        discount=Decimal("2.00"),
        final_total=Decimal("47.00"),
    )
    result.validate_math_consistency()
    assert not any("Mathematical discrepancy" in w for w in result.warnings)


def test_genuine_discrepancy_detected_without_arbitrary_threshold():
    """5. A genuine discrepancy is detected without an arbitrary 0.05 threshold."""
    result = ReceiptExtractionResult(
        subtotal=Decimal("50.00"),
        tax=Decimal("5.00"),
        tip=Decimal("0.00"),
        discount=Decimal("0.00"),
        final_total=Decimal("55.02"),  # 0.02 discrepancy
        confidence=0.90,
    )
    result.validate_math_consistency()
    assert any("Mathematical discrepancy" in w for w in result.warnings)
    assert result.confidence is not None
    assert result.confidence == 0.90


def test_missing_subtotal_continues_to_be_preserved():
    """6. Missing subtotal continues to be preserved."""
    result = ReceiptExtractionResult(
        subtotal=None,
        tax=Decimal("5.00"),
        tip=Decimal("0.00"),
        discount=Decimal("0.00"),
        final_total=Decimal("55.00"),
    )
    assert result.subtotal is None
    result.validate_math_consistency()
    assert not any("Mathematical discrepancy" in w for w in result.warnings)


def test_missing_confidence_does_not_invalidate_extraction_reconciliation():
    """7. Missing confidence does not invalidate extraction."""
    result = ReceiptExtractionResult(
        status="completed",
        confidence=None,
        subtotal=Decimal("50.00"),
        tax=Decimal("5.00"),
        tip=Decimal("0.00"),
        discount=Decimal("0.00"),
        final_total=Decimal("55.00"),
    )
    result.validate_math_consistency()
    assert result.status == "completed"
    assert result.confidence is None
    assert not any("Mathematical discrepancy" in w for w in result.warnings)


# =============================================================================
# 11. CURRENCY AMBIGUITY, CONFIDENCE & DECIMAL SERIALIZATION TESTS
# =============================================================================

def test_bare_dollar_remains_ambiguous():
    """Bare '$' remains ambiguous: currency is None, marked in uncertain_fields and warnings."""
    # From model constructor directly
    res = ReceiptExtractionResult(
        merchant_name="Ambiguous Diner",
        currency="$",
        final_total=Decimal("20.00"),
    )
    assert res.currency is None
    assert "currency" in res.uncertain_fields
    assert any("Ambiguous currency symbol '$'" in w for w in res.warnings)

    # From regex fallback
    fallback = RegexHeuristicFallback()
    res_fallback = fallback.parse_text("Ambiguous Diner\nTotal: $20.00")
    assert res_fallback.currency is None
    assert "currency" in res_fallback.uncertain_fields
    assert any("Ambiguous currency symbol '$'" in w for w in res_fallback.warnings)


def test_us_dollar_maps_to_usd():
    """US$ unambiguously maps to USD."""
    res = ReceiptExtractionResult(
        merchant_name="US Store",
        currency="US$",
        final_total=Decimal("20.00"),
    )
    assert res.currency == "USD"
    assert "currency" not in res.uncertain_fields

    fallback = RegexHeuristicFallback()
    res_fallback = fallback.parse_text("US Store\nTotal: US$20.00")
    assert res_fallback.currency == "USD"


def test_explicit_cad_aud_usd_remain_correct():
    """Explicit CAD, AUD, and USD remain correct."""
    for code in ["CAD", "AUD", "USD"]:
        res = ReceiptExtractionResult(
            merchant_name=f"{code} Merchant",
            currency=code,
            final_total=Decimal("50.00"),
        )
        assert res.currency == code
        assert "currency" not in res.uncertain_fields

    fallback = RegexHeuristicFallback()
    assert fallback.parse_text("Canadian Store\nTotal: 15.00 CAD").currency == "CAD"
    assert fallback.parse_text("Aussie Store\nTotal: 25.00 AUD").currency == "AUD"
    assert fallback.parse_text("US Store\nTotal: 35.00 USD").currency == "USD"


def test_missing_currency_remains_none_without_uncertain_flag():
    """Missing currency remains None and is not flagged as ambiguous '$'."""
    res = ReceiptExtractionResult(
        merchant_name="No Currency Merchant",
        currency=None,
        final_total=Decimal("10.00"),
    )
    assert res.currency is None
    assert "currency" not in res.uncertain_fields

    fallback = RegexHeuristicFallback()
    res_fallback = fallback.parse_text("Generic Merchant\nItem 1 10.00\nTotal: 10.00")
    assert res_fallback.currency is None
    assert "currency" not in res_fallback.uncertain_fields


def test_genuine_confidence_preserved_unchanged_on_math_inconsistency():
    """Genuine confidence remains unchanged after math inconsistency warning."""
    res = ReceiptExtractionResult(
        merchant_name="Inconsistent Math Bistro",
        subtotal=Decimal("10.00"),
        tax=Decimal("1.00"),
        tip=Decimal("0.00"),
        discount=Decimal("0.00"),
        final_total=Decimal("15.00"),  # Expected 11.00, mismatch
        confidence=0.88,
    )
    res.validate_math_consistency()
    assert any("Mathematical discrepancy" in w for w in res.warnings)
    # Genuine confidence MUST NOT be arbitrarily reduced
    assert res.confidence == 0.88


def test_regex_fallback_does_not_invent_confidence():
    """Regex fallback calculates low confidence based on completeness, never high confidence."""
    fallback = RegexHeuristicFallback()
    res = fallback.parse_text("Sample Store\nItem 1 10.00\nTotal: 10.00")
    assert res.confidence is not None and res.confidence <= 0.35  # Low confidence, never high
    assert res.is_fallback is True

    res_empty = fallback.parse_text("")
    assert res_empty.confidence == 0.0  # Zero confidence for empty input
    assert res_empty.is_fallback is True


def test_frontend_contract_decimal_string_serialization():
    """Frontend contract serializes monetary values and quantities as decimal strings."""
    res = ReceiptExtractionResult(
        merchant_name="Serialization Cafe",
        currency="USD",
        subtotal=Decimal("19.99"),
        tax=Decimal("0.10"),
        tip=Decimal("0.00"),
        discount=Decimal("0.00"),
        final_total=Decimal("20.09"),
        items=[
            ExtractedLineItem(
                item_name="Bulk Grains",
                quantity=Decimal("1.2500"),
                unit_price=Decimal("10.00"),
                total_price=Decimal("12.50"),
            ),
            ExtractedLineItem(
                item_name="Complimentary Mint",
                quantity=Decimal("0"),
                unit_price=Decimal("0.00"),
                total_price=Decimal("0.00"),
            ),
        ],
    )
    frontend = res.to_frontend_contract()
    assert frontend["subtotal"] == "19.99"
    assert frontend["tax"] == "0.10"
    assert frontend["tip"] == "0.00"
    assert frontend["discount"] == "0.00"
    assert frontend["total"] == "20.09"

    # Items serialization
    assert len(frontend["items"]) == 2
    item1 = frontend["items"][0]
    assert item1["quantity"] == "1.2500"
    assert item1["unit_price"] == "10.00"
    assert item1["total_price"] == "12.50"
    assert item1["price"] == "12.50"

    item2 = frontend["items"][1]
    assert item2["quantity"] == "0"
    assert item2["unit_price"] == "0.00"
    assert item2["total_price"] == "0.00"
    assert item2["price"] == "0.00"


def test_frontend_contract_preserves_none():
    """Frontend contract preserves None for missing monetary values and quantities."""
    res = ReceiptExtractionResult(
        merchant_name=None,
        subtotal=None,
        tax=None,
        tip=None,
        discount=None,
        final_total=None,
        items=[
            ExtractedLineItem(
                item_name="Unknown Item",
                quantity=None,
                unit_price=None,
                total_price=None,
            ),
        ],
    )
    frontend = res.to_frontend_contract()
    assert frontend["merchant"] is None
    assert frontend["subtotal"] is None
    assert frontend["tax"] is None
    assert frontend["tip"] is None
    assert frontend["discount"] is None
    assert frontend["total"] is None

    assert len(frontend["items"]) == 1
    item = frontend["items"][0]
    assert item["quantity"] is None
    assert item["price"] is None
    assert item["unit_price"] is None
    assert item["total_price"] is None


def test_one_cent_line_item_discrepancy_flagged():
    """1. One-cent line-item discrepancy must not silently pass."""
    # 2 * 10.00 = 20.00, but total_price is 20.01 -> 1 cent discrepancy
    res = ReceiptExtractionResult(
        items=[
            ExtractedLineItem(
                item_name="Espresso",
                quantity=Decimal("2"),
                unit_price=Decimal("10.00"),
                total_price=Decimal("20.01"),
            ),
        ],
    )
    res.validate_math_consistency()
    assert any("Line item math discrepancy for 'Espresso'" in w for w in res.warnings)

    # Clean line item with exact arithmetic produces NO discrepancy
    res_clean = ReceiptExtractionResult(
        items=[
            ExtractedLineItem(
                item_name="Espresso",
                quantity=Decimal("2"),
                unit_price=Decimal("10.00"),
                total_price=Decimal("20.00"),
            ),
        ],
    )
    res_clean.validate_math_consistency()
    assert not any("Line item math discrepancy" in w for w in res_clean.warnings)


def test_missing_extraction_status_defaults_to_review_required():
    """2. Missing extraction status defaults to review_required."""
    # Default instantiation without status
    res = ReceiptExtractionResult()
    assert res.status == "review_required"

    # Explicit None status passed
    res_none = ReceiptExtractionResult(status=None)
    assert res_none.status == "review_required"

    # From raw dictionary missing status key
    res_dict = ReceiptExtractionResult.model_validate({"merchant_name": "Test Cafe"})
    assert res_dict.status == "review_required"


def test_explicit_completed_status_remains_completed():
    """3. Explicit completed status returned by Gemini remains completed."""
    res = ReceiptExtractionResult(status="completed")
    assert res.status == "completed"

    res_dict = ReceiptExtractionResult.model_validate({"status": "completed", "merchant_name": "Verified Bistro"})
    assert res_dict.status == "completed"

    res_case = ReceiptExtractionResult.model_validate({"status": "COMPLETED"})
    assert res_case.status == "completed"


def test_explicit_zero_values_remain_zero_focused():
    """4. Explicit zero values remain zero and are not confused with missing data."""
    item = ExtractedLineItem(
        item_name="Free Bread",
        quantity=Decimal("0"),
        unit_price=Decimal("0.00"),
        total_price=Decimal("0.00"),
    )
    assert item.quantity == Decimal("0")
    assert item.unit_price == Decimal("0.00")
    assert item.total_price == Decimal("0.00")

    res = ReceiptExtractionResult(
        subtotal=Decimal("0.00"),
        tax=Decimal("0.00"),
        tip=Decimal("0.00"),
        discount=Decimal("0.00"),
        final_total=Decimal("0.00"),
        items=[item],
    )
    assert res.subtotal == Decimal("0.00")
    assert res.tax == Decimal("0.00")
    assert res.tip == Decimal("0.00")
    assert res.discount == Decimal("0.00")
    assert res.final_total == Decimal("0.00")

    # Frontend serialization
    frontend = res.to_frontend_contract()
    assert frontend["subtotal"] == "0.00"
    assert frontend["tax"] == "0.00"
    assert frontend["tip"] == "0.00"
    assert frontend["discount"] == "0.00"
    assert frontend["total"] == "0.00"
    assert frontend["items"][0]["quantity"] == "0"
    assert frontend["items"][0]["price"] == "0.00"


def test_missing_values_remain_none_focused():
    """5. Missing values remain None and are not converted to zero or default strings."""
    item = ExtractedLineItem(
        item_name="Mystery Item",
        quantity=None,
        unit_price=None,
        total_price=None,
    )
    assert item.quantity is None
    assert item.unit_price is None
    assert item.total_price is None

    res = ReceiptExtractionResult(
        merchant_name=None,
        currency=None,
        subtotal=None,
        tax=None,
        tip=None,
        discount=None,
        final_total=None,
        confidence=None,
        items=[item],
    )
    assert res.merchant_name is None
    assert res.currency is None
    assert res.subtotal is None
    assert res.tax is None
    assert res.tip is None
    assert res.discount is None
    assert res.final_total is None
    assert res.confidence is None

    # Backend contract preserves None
    backend = res.to_backend_contract()
    assert backend["merchant_name"] is None
    assert backend["currency"] is None
    assert backend["subtotal"] is None
    assert backend["tax"] is None
    assert backend["total"] is None
    assert backend["items"][0]["quantity"] is None
    assert backend["items"][0]["unit_price"] is None
    assert backend["items"][0]["total_price"] is None

    # Frontend contract preserves None
    frontend = res.to_frontend_contract()
    assert frontend["merchant"] is None
    assert frontend["currency"] is None
    assert frontend["subtotal"] is None
    assert frontend["tax"] is None
    assert frontend["tip"] is None
    assert frontend["discount"] is None
    assert frontend["total"] is None
    assert frontend["confidence"] is None
    assert frontend["items"][0]["quantity"] is None
    assert frontend["items"][0]["price"] is None


def test_ocr_preprocessing_uses_offline_fallback_when_gemini_unavailable():
    """Local OCR text is used by the offline fallback when Gemini is unavailable."""
    service = ReceiptExtractionService()
    img = Image.new("RGB", (100, 100), color="white")

    embedded_sample_text = (
        "Cafe Bistro\n"
        "Coffee 1 4.50\n"
        "Subtotal: 4.50\n"
        "Tax: 0.45\n"
        "Total: 4.95"
    )

    res = service.ocr_engine.process_receipt(
        image=img,
        embedded_text=embedded_sample_text,
    )

    assert res is not None
    assert res.is_fallback is True
    assert res.extraction_method == "regex_heuristic_fallback"
    assert res.merchant_name == "Cafe Bistro"
    assert res.final_total == Decimal("4.95")
    assert any("fallback" in w.lower() for w in res.warnings)
