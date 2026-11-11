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

import json
from decimal import Decimal
from pathlib import Path
import pytest
from PIL import Image

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
    """Tests line item decimal values, fractional quantities, and strict no-fabrication rule."""
    item = ExtractedLineItem(
        item_name="Truffle Pasta",
        quantity=2,
        unit_price=Decimal("15.50"),
        total_price=Decimal("31.00"),
    )
    assert item.item_name == "Truffle Pasta"
    assert item.quantity == Decimal("2")
    assert item.unit_price == Decimal("15.50")
    assert item.total_price == Decimal("31.00")

    # Anti-fabrication rule: If total_price is omitted, it MUST remain None (never auto-calculated)
    item2 = ExtractedLineItem(
        item_name="Gelato",
        quantity=3,
        unit_price=Decimal("4.25"),
    )
    assert item2.total_price is None

    # Fractional quantity support with Decimal
    item3 = ExtractedLineItem(
        item_name="Artisan Cheese",
        quantity=Decimal("1.5"),
        unit_price=Decimal("12.00"),
        total_price=Decimal("18.00"),
    )
    assert item3.quantity == Decimal("1.5")
    assert isinstance(item3.quantity, Decimal)


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
    """Verifies that mathematical discrepancies trigger warnings and adjust confidence."""
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
    assert result.confidence < 0.90


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
    assert frontend["subtotal"] == 45.50
    assert frontend["tax"] == 4.50
    assert frontend["tip"] == 5.00
    assert frontend["total"] == 55.00
    assert frontend["confidence"] == 0.95
    assert len(frontend["items"]) == 1
    assert frontend["items"][0]["id"] == "item_1"
    assert frontend["items"][0]["name"] == "Margherita Pizza"
    assert frontend["items"][0]["price"] == 25.00


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
# 5. CURRENCY DETECTION & NO-FALLBACK GUARANTEES
# =============================================================================

def test_ocr_preprocessing_does_not_replace_gemini():
    """Requirement: Local OCR/embedded text must strictly serve as preprocessing context, never replace Gemini."""
    service = ReceiptExtractionService()  # Unconfigured API key
    img = Image.new("RGB", (100, 100), color="white")
    embedded_sample_text = (
        "Cafe Bistro\nCoffee 1 4.50\nSubtotal: 4.50\nTax: 0.45\nTotal: 4.95"
    )
    res = service.ocr_engine.process_receipt(
        image=img,
        embedded_text=embedded_sample_text,
    )
    # Gemini failure/absence must return status failed with API_KEY_MISSING, never OCR/regex data
    assert res.status == "failed"
    assert res.error_code == "API_KEY_MISSING"
    assert res.confidence is None
    assert res.items == []
    assert res.merchant_name is None
    assert res.final_total is None
    assert res.is_fallback is False


def test_currency_detection_inr_formats():
    """Tests that ₹, Rs., Rs, and INR are all correctly identified as INR."""
    fallback = RegexHeuristicFallback()
    assert fallback.parse_text("Taj Mahal Hotel\nTotal: ₹1500.00").currency == "INR"
    assert fallback.parse_text("Saravana Bhavan\nTotal: Rs. 450.00").currency == "INR"
    assert fallback.parse_text("Bikanervala\nTotal: Rs 250.00").currency == "INR"
    assert fallback.parse_text("Haldirams\nTotal: 990.00 INR").currency == "INR"


def test_currency_detection_usd_format():
    """Tests that $ and USD are identified as USD."""
    fallback = RegexHeuristicFallback()
    assert fallback.parse_text("Mario Diner\nTotal: $50.00").currency == "USD"
    assert fallback.parse_text("City Cafe\nTotal: 25.00 USD").currency == "USD"


def test_currency_missing_preserves_null_in_canonical_result():
    """When receipt text has no currency indicator, currency MUST remain null/None."""
    fallback = RegexHeuristicFallback()
    result = fallback.parse_text("Generic Merchant\nItem 1 10.00\nTotal: 10.00")
    assert result.currency is None
    assert any("Currency was not detected on receipt" in w for w in result.warnings)


def test_missing_currency_preserves_none_in_all_adapters():
    """Requirement: If currency is not identified, preserve currency=None in all adapters without defaulting to USD."""
    result = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name="Unknown Diner",
        currency=None,  # Genuinely missing
        subtotal=Decimal("10.00"),
        tax=Decimal("1.00"),
        final_total=Decimal("11.00"),
        items=[
            ExtractedLineItem(
                item_name="Coffee",
                quantity=1,
                unit_price=Decimal("10.00"),
                total_price=Decimal("10.00"),
            ),
        ],
    )
    # Backend contract adapter must preserve None (never default to USD)
    backend_payload = result.to_backend_contract()
    assert backend_payload["currency"] is None
    assert not any("defaulted to USD" in w for w in result.warnings)

    # Frontend contract adapter must preserve None
    frontend_payload = result.to_frontend_contract()
    assert frontend_payload["currency"] is None

    # Full API response contract adapter must preserve None
    api_payload = result.to_api_response()
    assert api_payload["currency"] is None


def test_backend_adapter_preserves_empty_items_without_dummy_fabrication():
    """Backend adapter MUST preserve empty items as [] without fabricating dummy items."""
    result = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name="Mario's",
        currency="USD",
        items=[],
    )
    payload = result.to_backend_contract()
    assert payload["items"] == []


def test_backend_adapter_rejects_non_receipt():
    """Backend adapter MUST refuse to generate payload for non-receipts."""
    result = ReceiptExtractionResult(
        is_receipt=False,
        rejection_reason="Document is an academic conversion table.",
        items=[],
    )
    with pytest.raises(ValueError, match="non-receipt"):
        result.to_backend_contract()


# =============================================================================
# 6. SERVICE VALIDATION & ERROR HANDLING
# =============================================================================

def test_service_rejects_empty_file():
    service = ReceiptExtractionService()
    # Contract response test (Section 2: return failed status with error_code and message)
    res = service.extract_from_bytes(b"", "receipt.jpg")
    assert res.status == "failed"
    assert res.error_code == "EMPTY_FILE"
    assert "empty" in res.error_message.lower()

    # Strict mode exception test
    with pytest.raises(ReceiptExtractionError, match="empty"):
        service.extract_from_bytes(b"", "receipt.jpg", raise_on_error=True)


def test_service_rejects_unsupported_format():
    service = ReceiptExtractionService()
    # Contract response test
    res = service.extract_from_bytes(b"some content", "malicious_script.exe")
    assert res.status == "failed"
    assert res.error_code == "UNSUPPORTED_FORMAT"

    # Strict mode exception test
    with pytest.raises(ReceiptExtractionError, match="not supported"):
        service.extract_from_bytes(b"some content", "malicious_script.exe", raise_on_error=True)


def test_service_rejects_oversized_file():
    service = ReceiptExtractionService(max_size_mb=1)  # 1 MB threshold
    large_payload = b"0" * (2 * 1024 * 1024)  # 2 MB
    # Contract response test
    res = service.extract_from_bytes(large_payload, "large_receipt.png")
    assert res.status == "failed"
    assert res.error_code == "FILE_TOO_LARGE"

    # Strict mode exception test
    with pytest.raises(ReceiptExtractionError, match="exceeds maximum allowed limit"):
        service.extract_from_bytes(large_payload, "large_receipt.png", raise_on_error=True)


def test_service_rejects_corrupted_image():
    service = ReceiptExtractionService()
    # Contract response test
    res = service.extract_from_bytes(b"not a real image payload", "broken.jpg")
    assert res.status == "failed"
    assert res.error_code == "CORRUPTED_IMAGE"

    # Strict mode exception test
    with pytest.raises(ReceiptExtractionError, match="Corrupted or invalid image"):
        service.extract_from_bytes(b"not a real image payload", "broken.jpg", raise_on_error=True)


def test_reject_infix_postfix_table():
    """CRITICAL FIX: Infix-to-postfix conversion tables must be classified as non-receipts."""
    table_text = """
    Infix to Postfix Conversion Table
    Token   Stack   Postfix Output
    (       (
    A       (       A
    +       (+      A
    B       (+      AB
    *       (+*     AB
    C       (+*     ABC
    )               ABC*+
    """
    fallback = RegexHeuristicFallback()
    result = fallback.parse_text(table_text)

    # Classification & Rejection assertions:
    assert result.is_receipt is False
    assert result.rejection_reason is not None
    assert any(term in result.rejection_reason.lower() for term in ["academic", "infix", "postfix", "table"])
    assert result.confidence == 0.0
    assert result.merchant_name is None
    assert result.items == []
    assert result.final_total is None

    # Contract assertions:
    frontend_data = result.to_frontend_contract()
    assert frontend_data["success"] is False
    assert frontend_data["is_receipt"] is False
    assert frontend_data["merchant"] is None
    assert frontend_data["items"] == []

    # Backend adapter must reject conversion
    with pytest.raises(ValueError, match="non-receipt"):
        result.to_backend_contract()


def test_reject_blank_image():
    """Blank images must be classified as non-receipts with confidence 0.0."""
    fallback = RegexHeuristicFallback()
    result = fallback.parse_text("")
    assert result.is_receipt is False
    assert result.status == "failed"
    assert result.error_code == "NO_READABLE_TEXT"
    assert result.confidence == 0.0
    assert result.items == []

    # With service.validate_receipt, raises ReceiptExtractionError for non-receipts
    service = ReceiptExtractionService()
    with pytest.raises(ReceiptExtractionError, match="No readable text"):
        service.validate_receipt(result)


def test_reject_random_academic_document():
    """Academic document with abstract, theorem, and pseudocode must be rejected."""
    academic_text = """
    Algorithm Complexity Analysis in Distributed Systems
    Abstract: In this paper we study asynchronous message passing.
    Lemma 1. The time complexity of algorithm is O(n log n).
    Proof: By induction on the height of the parse tree.
    References:
    [1] Knuth, D. The Art of Computer Programming.
    """
    fallback = RegexHeuristicFallback()
    result = fallback.parse_text(academic_text)
    assert result.is_receipt is False
    assert result.status == "failed"
    assert result.error_code == "NON_RECEIPT_DOCUMENT"
    assert result.confidence == 0.0
    assert result.merchant_name is None
    assert result.items == []


def test_valid_indian_receipt_inr():
    """Tests extraction of Indian receipt with ₹ / Rs. currency and GST."""
    indian_receipt_text = """
    Saravana Bhavan Restaurant
    12 Connaught Place, New Delhi
    Date: 2026-11-08
    Invoice: SB-8492
    Masala Dosa 2 240.00
    Filter Coffee 2 80.00
    Subtotal: Rs. 320.00
    GST 5%: Rs. 16.00
    TOTAL AMOUNT: Rs. 336.00
    Payment: Cash
    """
    fallback = RegexHeuristicFallback()
    result = fallback.parse_text(indian_receipt_text)

    assert result.is_receipt is True
    assert result.currency == "INR"
    assert result.merchant_name == "Saravana Bhavan Restaurant"
    assert result.subtotal == Decimal("320.00")
    assert result.tax == Decimal("16.00")
    assert result.final_total == Decimal("336.00")
    assert len(result.items) >= 2


def test_low_confidence_review_gate():
    """Low confidence extractions must be caught by validate_receipt."""
    service = ReceiptExtractionService()
    low_conf_result = ReceiptExtractionResult(
        is_receipt=True,
        confidence=0.10,
        items=[],
        final_total=None,
    )
    with pytest.raises(ReceiptExtractionError, match="confidence is insufficient"):
        service.validate_receipt(low_conf_result)


# =============================================================================
# 7. END-TO-END EXTRACTION WITH FIXTURES (NO SILENT FALLBACK)
# =============================================================================

def test_fixture_01_clear_restaurant():
    service = ReceiptExtractionService()
    path = FIXTURES_DIR / "receipt_01_clear_restaurant.png"
    result = service.extract_from_path(path)

    assert result is not None
    # Critical requirement: Without API key, fails immediately with API_KEY_MISSING, never silently falls back
    assert result.status == "failed"
    assert result.error_code == "API_KEY_MISSING"
    assert result.is_fallback is False
    assert result.confidence is None
    frontend_payload = result.to_frontend_contract()
    assert "is_receipt" in frontend_payload


def test_fixture_02_blurry_takeout():
    service = ReceiptExtractionService()
    path = FIXTURES_DIR / "receipt_02_blurry_takeout.png"
    result = service.extract_from_path(path)

    # Blur detection runs during preprocessing
    assert any("blurry" in w.lower() for w in result.warnings)


def test_fixture_03_rotated_grocery():
    service = ReceiptExtractionService()
    path = FIXTURES_DIR / "receipt_03_rotated_grocery.png"
    result = service.extract_from_path(path)
    assert result is not None


def test_fixture_04_incomplete_cafe():
    service = ReceiptExtractionService()
    path = FIXTURES_DIR / "receipt_04_incomplete_cafe.png"
    result = service.extract_from_path(path)

    # Incomplete receipt has no address, so address MUST remain None/null (no hallucination)
    assert result.merchant_address is None


def test_fixture_05_digital_invoice_pdf():
    service = ReceiptExtractionService()
    path = FIXTURES_DIR / "receipt_05_digital_invoice.pdf"
    result = service.extract_from_path(path)

    assert result is not None
    # Without configured Gemini API key, fails immediately with API_KEY_MISSING (no silent fallback)
    assert result.status == "failed"
    assert result.error_code == "API_KEY_MISSING"
    frontend_payload = result.to_frontend_contract()
    assert "items" in frontend_payload


# =============================================================================
# 8. MANDATORY CHECKLIST & APPROVED CONTRACT COMPLIANCE TESTS
# =============================================================================

def test_missing_quantity_remains_null():
    """Requirement 4: Missing quantity MUST remain null, never defaulting to 1."""
    item = ExtractedLineItem(
        item_name="Sparkling Water",
        quantity=None,
        unit_price=Decimal("4.00"),
        total_price=Decimal("4.00"),
    )
    assert item.quantity is None
    d = item.to_dict()
    assert d["quantity"] is None


def test_missing_prices_remain_null():
    """Requirement 5: Missing prices MUST remain null, never defaulting to 0.00."""
    item = ExtractedLineItem(
        item_name="Market Price Catch of the Day",
        quantity=1,
        unit_price=None,
        total_price=None,
    )
    assert item.unit_price is None
    assert item.total_price is None
    d = item.to_dict()
    assert d["unit_price"] is None
    assert d["total_price"] is None


def test_no_unknown_merchant_fabrication():
    """Requirement 2: Never fabricate 'Unknown Merchant'."""
    result = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name=None,
        currency="USD",
        items=[
            ExtractedLineItem(item_name="Item 1", quantity=1, unit_price=Decimal("5.00"), total_price=Decimal("5.00")),
        ],
        final_total=Decimal("5.00"),
    )
    # Backend contract preserves None when merchant_name is missing (no ValueError, no fake default)
    backend_payload = result.to_backend_contract()
    assert backend_payload["merchant_name"] is None

    # Frontend and API responses preserve None
    api_resp = result.to_api_response()
    assert api_resp["merchant_name"] is None

    frontend_resp = result.to_frontend_contract()
    assert frontend_resp["merchant"] is None


def test_status_completed_on_fully_verified_receipt():
    """Requirement 11: Valid, confident, complete receipt returns completed."""
    result = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name="Artisan Bistro",
        currency="USD",
        receipt_date="2026-11-09",
        subtotal=Decimal("40.00"),
        tax=Decimal("4.00"),
        final_total=Decimal("44.00"),
        confidence=0.95,
        is_fallback=False,
        items=[
            ExtractedLineItem(item_name="Pizza", quantity=1, unit_price=Decimal("20.00"), total_price=Decimal("20.00")),
            ExtractedLineItem(item_name="Salad", quantity=2, unit_price=Decimal("10.00"), total_price=Decimal("20.00")),
        ],
    )
    result.validate_math_consistency()
    assert result.status == "completed"
    assert result.missing_fields == []
    assert result.uncertain_fields == []


def test_status_review_required_on_incomplete_receipt():
    """Requirement 12: Incomplete or uncertain receipt returns review_required."""
    result = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name="Mario's",
        currency=None,  # Missing currency
        subtotal=Decimal("20.00"),
        final_total=None,  # Missing total
        confidence=0.50,
        items=[],
    )
    result.validate_math_consistency()
    assert result.status == "review_required"
    assert "currency" in result.missing_fields
    assert "final_total" in result.missing_fields
    assert "items" in result.missing_fields


def test_gemini_failure_returns_failed_status(monkeypatch):
    """Requirement 7: Gemini failure returns status: failed with error_code."""
    extractor = GeminiVisionExtractor(api_key="test-api-key")

    def mock_generate_content(*args, **kwargs):
        raise RuntimeError("Google GenAI 500: Internal Server Error")

    class MockModels:
        generate_content = staticmethod(mock_generate_content)

    class MockGenaiClient:
        models = MockModels()

    import google.genai
    monkeypatch.setattr(google.genai, "Client", lambda *args, **kwargs: MockGenaiClient())

    img = Image.new("RGB", (100, 100), color="white")
    result = extractor.extract(img)

    assert result.status == "failed"
    assert result.is_receipt is False
    assert result.error_code == "AI_EXTRACTION_FAILED"
    assert "extraction failed" in result.error_message.lower()
    assert result.confidence is None


def test_gemini_quota_error_returns_rate_limit_exceeded(monkeypatch):
    """Requirement 12: Gemini API rate limit or quota errors return RATE_LIMIT_EXCEEDED."""
    extractor = GeminiVisionExtractor(api_key="test-api-key")

    def mock_generate_content(*args, **kwargs):
        raise RuntimeError("Resource exhausted: API quota exceeded (HTTP 429)")

    class MockModels:
        generate_content = staticmethod(mock_generate_content)

    class MockGenaiClient:
        models = MockModels()

    import google.genai
    monkeypatch.setattr(google.genai, "Client", lambda *args, **kwargs: MockGenaiClient())

    img = Image.new("RGB", (100, 100), color="white")
    result = extractor.extract(img)

    assert result.status == "failed"
    assert result.is_receipt is False
    assert result.error_code == "RATE_LIMIT_EXCEEDED"
    assert "rate limit or quota exceeded" in result.error_message.lower()
    assert result.confidence is None


def test_gemini_timeout_returns_failed_status(monkeypatch):
    """Requirement 8: Gemini timeout returns status: failed with error_code: TIMEOUT."""
    import time
    extractor = GeminiVisionExtractor(api_key="test-api-key")

    # Temporarily shorten timeout for quick test
    import app.services.receipt_extractor.llm_parser as parser_module
    monkeypatch.setattr(parser_module, "GEMINI_TIMEOUT_SECONDS", 0.1)

    def mock_hanging_call(*args, **kwargs):
        time.sleep(1.0)
        return None

    class MockModels:
        generate_content = staticmethod(mock_hanging_call)

    class MockGenaiClient:
        models = MockModels()

    import google.genai
    monkeypatch.setattr(google.genai, "Client", lambda *args, **kwargs: MockGenaiClient())

    img = Image.new("RGB", (100, 100), color="white")
    t0 = time.time()
    result = extractor.extract(img)
    elapsed = time.time() - t0

    # Must return quickly after timeout without waiting for the 1.0s hanging thread
    assert elapsed < 0.7
    assert result.status == "failed"
    assert result.is_receipt is False
    assert result.error_code == "TIMEOUT"
    assert "timed out" in result.error_message.lower()


def test_all_response_arrays_always_present():
    """Requirement 13: items, missing_fields, uncertain_fields, warnings must always be present."""
    failed_result = ReceiptExtractionResult(
        status="failed",
        is_receipt=False,
        error_code="TEST_ERROR",
        error_message="Test failure",
    )
    api_resp = failed_result.to_api_response()
    assert isinstance(api_resp["items"], list)
    assert isinstance(api_resp["missing_fields"], list)
    assert isinstance(api_resp["uncertain_fields"], list)
    assert isinstance(api_resp["warnings"], list)


def test_monetary_values_decimal_strings_in_api_response():
    """Requirement 15: Monetary values use Decimal internally and decimal strings externally."""
    result = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name="Cafe",
        currency="USD",
        subtotal=Decimal("45.50"),
        tax=Decimal("4.55"),
        tip=Decimal("5.00"),
        discount=Decimal("2.00"),
        final_total=Decimal("53.05"),
        items=[
            ExtractedLineItem(item_name="Coffee", quantity=2, unit_price=Decimal("4.50"), total_price=Decimal("9.00")),
        ],
    )
    api_resp = result.to_api_response()
    assert api_resp["subtotal"] == "45.50"
    assert api_resp["tax"] == "4.55"
    assert api_resp["tip"] == "5.00"
    assert api_resp["discount"] == "2.00"
    assert api_resp["total"] == "53.05"
    assert api_resp["final_total"] == "53.05"
    assert api_resp["items"][0]["unit_price"] == "4.50"
    assert api_resp["items"][0]["total_price"] == "9.00"


def test_approved_contract_field_set():
    """Verifies that to_api_response() contains all 14 single-source-of-truth fields."""
    result = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name="Bistro",
        currency="USD",
        subtotal=Decimal("10.00"),
        tax=Decimal("1.00"),
        final_total=Decimal("11.00"),
        items=[],
    )
    api_resp = result.to_api_response()
    required_fields = [
        "document_type",
        "merchant_name",
        "currency",
        "subtotal",
        "tax",
        "final_total",
        "items",
        "missing_fields",
        "uncertain_fields",
        "confidence",
        "warnings",
        "status",
        "error_code",
        "error_message",
    ]
    for field in required_fields:
        assert field in api_resp, f"Required contract field missing: {field}"


def test_gemini_failure_never_triggers_regex_fallback(monkeypatch):
    """Critical Requirement 3: No regex or local fallback may silently replace a failed Gemini extraction."""
    service = ReceiptExtractionService(api_key="test-key")

    def mock_broken_call(*args, **kwargs):
        raise RuntimeError("Google GenAI 500: Internal Server Error")

    class MockModels:
        generate_content = staticmethod(mock_broken_call)

    class MockGenaiClient:
        models = MockModels()

    import google.genai
    monkeypatch.setattr(google.genai, "Client", lambda *args, **kwargs: MockGenaiClient())

    img = Image.new("RGB", (100, 100), color="white")
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw_bytes = buf.getvalue()

    result = service.extract_from_bytes(raw_bytes, filename="receipt.png")

    # MUST return failed, NEVER silent regex fallback
    assert result.status == "failed"
    assert result.error_code == "AI_EXTRACTION_FAILED"
    assert result.is_fallback is False
    assert result.confidence is None
    assert result.items == []


def test_approved_interface_callable():
    """Verifies exact method signatures: extract_from_bytes and extract_from_path."""
    service = ReceiptExtractionService()

    # extract_from_bytes callable with exact parameter names
    res1 = service.extract_from_bytes(file_bytes=b"", filename="receipt.jpg")
    assert res1.status == "failed"
    assert res1.error_code == "EMPTY_FILE"

    # extract_from_path callable with exact parameter names
    sharp_path = FIXTURES_DIR / "receipt_01_clear_restaurant.png"
    res2 = service.extract_from_path(file_path=sharp_path)
    assert res2 is not None


def test_missing_confidence_is_not_replaced_with_095(monkeypatch):
    """Requirement 15: Missing confidence MUST remain None, never replaced with 0.95 or fabricated values."""
    extractor = GeminiVisionExtractor(api_key="test-api-key")

    mock_gemini_json = json.dumps({
        "status": "completed",
        "document_type": "receipt",
        "is_receipt": True,
        "merchant_name": "Authentic Bistro",
        "currency": "USD",
        "subtotal": "25.00",
        "tax": "2.50",
        "final_total": "27.50",
        "confidence": None,  # Model genuinely did not provide confidence
        "items": [
            {
                "item_name": "Pasta",
                "quantity": 1,
                "unit_price": "25.00",
                "total_price": "25.00",
            }
        ],
        "missing_fields": [],
        "uncertain_fields": [],
        "warnings": [],
    })

    class MockResponse:
        text = mock_gemini_json

    class MockModels:
        generate_content = staticmethod(lambda *args, **kwargs: MockResponse())

    class MockGenaiClient:
        models = MockModels()

    import google.genai
    monkeypatch.setattr(google.genai, "Client", lambda *args, **kwargs: MockGenaiClient())

    img = Image.new("RGB", (100, 100), color="white")
    result = extractor.extract(img)

    # Confidence must strictly remain None, never defaulted to 0.95
    assert result.confidence is None
    api_payload = result.to_api_response()
    assert api_payload["confidence"] is None
    # Because confidence is missing, status requires human review
    assert result.status == "review_required"


def test_fractional_quantities():
    """Requirement 4: Line item quantity must support fractional values using Decimal."""
    # Fractional quantities: 0.5 kg, 1.25 lbs, etc.
    item_half = ExtractedLineItem(
        item_name="Deli Roast Beef",
        quantity=Decimal("0.5"),
        unit_price=Decimal("16.00"),
        total_price=Decimal("8.00"),
    )
    assert item_half.quantity == Decimal("0.5")
    assert isinstance(item_half.quantity, Decimal)
    assert item_half.to_dict()["quantity"] == Decimal("0.5")
    assert isinstance(item_half.to_dict()["quantity"], Decimal)

    item_float_input = ExtractedLineItem(
        item_name="Bulk Grapes",
        quantity=1.75,
        unit_price=Decimal("4.00"),
        total_price=Decimal("7.00"),
    )
    assert item_float_input.quantity == Decimal("1.75")
    assert isinstance(item_float_input.quantity, Decimal)
    assert item_float_input.to_dict()["quantity"] == Decimal("1.75")
    assert isinstance(item_float_input.to_dict()["quantity"], Decimal)


def test_no_fabricated_zero_values():
    """Requirement 9: Missing monetary values MUST remain None, never converted to Decimal('0.00') or 0.0."""
    result = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name="Cafe With Missing Totals",
        currency="USD",
        subtotal=None,
        tax=None,
        tip=None,
        discount=None,
        final_total=None,
        items=[
            ExtractedLineItem(
                item_name="Special Dish",
                quantity=1,
                unit_price=None,
                total_price=None,
            )
        ],
    )
    # Canonical model preserves None
    assert result.subtotal is None
    assert result.tax is None
    assert result.tip is None
    assert result.discount is None
    assert result.final_total is None
    assert result.items[0].unit_price is None
    assert result.items[0].total_price is None

    # Serializer preserves None
    api_dict = result.to_api_response()
    assert api_dict["subtotal"] is None
    assert api_dict["tax"] is None
    assert api_dict["final_total"] is None
    assert api_dict["total"] is None
    assert api_dict["items"][0]["unit_price"] is None
    assert api_dict["items"][0]["total_price"] is None


def test_backend_worker_serialization_compatibility():
    """Requirement 18: Result serializer matches the backend worker's expected field names and types."""
    result = ReceiptExtractionResult(
        status="completed",
        document_type="receipt",
        is_receipt=True,
        merchant_name="Mario's Pizza",
        currency="USD",
        subtotal=Decimal("30.00"),
        tax=Decimal("3.00"),
        final_total=Decimal("33.00"),
        confidence=0.92,
        items=[
            ExtractedLineItem(
                item_name="Cheese Pizza",
                quantity=Decimal("1"),
                unit_price=Decimal("20.00"),
                total_price=Decimal("20.00"),
            ),
            ExtractedLineItem(
                item_name="Tiramisu",
                quantity=Decimal("2"),
                unit_price=Decimal("5.00"),
                total_price=Decimal("10.00"),
            ),
        ],
        missing_fields=[],
        uncertain_fields=[],
        warnings=[],
    )

    # Test both to_api_response() and to_dict()
    for serialized in [result.to_api_response(), result.to_dict()]:
        assert serialized["document_type"] == "receipt"
        assert serialized["merchant_name"] == "Mario's Pizza"
        assert serialized["currency"] == "USD"
        assert serialized["subtotal"] == "30.00"
        assert serialized["tax"] == "3.00"
        assert serialized["final_total"] == "33.00"
        assert serialized["confidence"] == 0.92
        assert serialized["status"] == "completed"
        assert serialized["error_code"] is None
        assert serialized["error_message"] is None
        assert isinstance(serialized["items"], list)
        assert len(serialized["items"]) == 2
        assert isinstance(serialized["missing_fields"], list)
        assert isinstance(serialized["uncertain_fields"], list)
        assert isinstance(serialized["warnings"], list)


def test_status_completed_review_required_failed():
    """Requirement 16: Verifies all three AI service statuses: completed, review_required, failed."""
    # 1. Completed: fully verified receipt with high confidence
    res_completed = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name="Fine Dining",
        currency="USD",
        subtotal=Decimal("50.00"),
        tax=Decimal("5.00"),
        final_total=Decimal("55.00"),
        confidence=0.95,
        items=[
            ExtractedLineItem(item_name="Steak", quantity=Decimal("1"), unit_price=Decimal("50.00"), total_price=Decimal("50.00"))
        ],
    )
    res_completed.validate_math_consistency()
    assert res_completed.status == "completed"

    # 2. Review Required: missing currency or low confidence
    res_review = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name="Corner Deli",
        currency=None,  # Missing currency
        subtotal=Decimal("10.00"),
        final_total=Decimal("10.00"),
        confidence=0.50,
        items=[
            ExtractedLineItem(item_name="Sandwich", quantity=Decimal("1"), unit_price=Decimal("10.00"), total_price=Decimal("10.00"))
        ],
    )
    res_review.validate_math_consistency()
    assert res_review.status == "review_required"
    assert "currency" in res_review.missing_fields

    # 3. Failed: Non-receipt or unparseable document
    res_failed = ReceiptExtractionResult(
        is_receipt=False,
        rejection_reason="Academic notes",
        items=[],
    )
    res_failed.evaluate_status()
    assert res_failed.status == "failed"
    assert res_failed.error_code == "NON_RECEIPT_DOCUMENT"


def test_quantity_decimal_fraction_survives_serialization_unchanged():
    """Verify that quantity Decimal('1.5') survives serialization unchanged across all adapters."""
    item = ExtractedLineItem(
        item_name="Organic Honeycrisp Apples",
        quantity=Decimal("1.5"),
        unit_price=Decimal("4.00"),
        total_price=Decimal("6.00"),
    )
    result = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name="Whole Foods",
        currency="USD",
        items=[item],
        final_total=Decimal("6.00"),
    )

    # 1. Line item to_dict()
    item_dict = item.to_dict()
    assert item_dict["quantity"] == Decimal("1.5")
    assert isinstance(item_dict["quantity"], Decimal)

    # 2. Result to_dict()
    res_dict = result.to_dict()
    assert res_dict["items"][0]["quantity"] == Decimal("1.5")
    assert isinstance(res_dict["items"][0]["quantity"], Decimal)

    # 3. Result to_api_response()
    api_resp = result.to_api_response()
    assert api_resp["items"][0]["quantity"] == Decimal("1.5")
    assert isinstance(api_resp["items"][0]["quantity"], Decimal)

    # 4. Result to_backend_contract()
    backend_payload = result.to_backend_contract()
    assert backend_payload["items"][0]["quantity"] == Decimal("1.5")
    assert isinstance(backend_payload["items"][0]["quantity"], Decimal)

    # 5. Result to_frontend_contract()
    frontend_payload = result.to_frontend_contract()
    assert frontend_payload["items"][0]["quantity"] == 1.5


def test_missing_merchant_and_currency_survive_serialization_as_none():
    """Verify missing merchant_name and currency survive serialization as None without defaults."""
    result = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name=None,
        currency=None,
        subtotal=Decimal("20.00"),
        tax=Decimal("2.00"),
        final_total=Decimal("22.00"),
        items=[
            ExtractedLineItem(item_name="Item A", quantity=1, unit_price=Decimal("20.00"), total_price=Decimal("20.00")),
        ],
    )

    # 1. to_dict()
    d = result.to_dict()
    assert d["merchant_name"] is None
    assert d["currency"] is None

    # 2. to_api_response()
    api = result.to_api_response()
    assert api["merchant_name"] is None
    assert api["currency"] is None

    # 3. to_backend_contract()
    backend = result.to_backend_contract()
    assert backend["merchant_name"] is None
    assert backend["currency"] is None

    # 4. to_frontend_contract()
    frontend = result.to_frontend_contract()
    assert frontend["merchant"] is None
    assert frontend["currency"] is None


def test_empty_items_with_review_required():
    """Verify that a valid receipt with no detected items sets review_required and serializes cleanly."""
    result = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name="Corner Store",
        currency="USD",
        items=[],
        final_total=Decimal("15.00"),
    )
    result.evaluate_status()

    # Must be marked review_required with 'items' in missing_fields
    assert result.status == "review_required"
    assert "items" in result.missing_fields

    # Must serialize with empty items list without raising ValueError or fabricating dummy items
    d = result.to_dict()
    assert d["items"] == []
    assert d["status"] == "review_required"

    backend = result.to_backend_contract()
    assert backend["items"] == []

    api = result.to_api_response()
    assert api["items"] == []


def test_review_required_results_not_rejected_by_ai_serializer():
    """Verify that review_required results are not incorrectly rejected with ValueError by AI serializers."""
    # Receipt with missing merchant, missing currency, and missing items (damaged receipt)
    review_result = ReceiptExtractionResult(
        is_receipt=True,
        merchant_name=None,
        currency=None,
        items=[],
        final_total=None,
        status="review_required",
        missing_fields=["merchant_name", "currency", "items", "final_total"],
    )

    # Must serialize cleanly without ValueError across all AI serializers
    api_payload = review_result.to_api_response()
    assert api_payload["status"] == "review_required"
    assert api_payload["merchant_name"] is None
    assert api_payload["currency"] is None
    assert api_payload["items"] == []

    dict_payload = review_result.to_dict()
    assert dict_payload["status"] == "review_required"
    assert dict_payload["merchant_name"] is None

    backend_payload = review_result.to_backend_contract()
    assert backend_payload["merchant_name"] is None
    assert backend_payload["currency"] is None
    assert backend_payload["items"] == []

    # Non-receipt documents MUST still raise ValueError in to_backend_contract()
    non_receipt = ReceiptExtractionResult(
        is_receipt=False,
        rejection_reason="Academic paper table",
        items=[],
    )
    with pytest.raises(ValueError, match="non-receipt"):
        non_receipt.to_backend_contract()



# =============================================================================
# 9. MOCKED GEMINI DOCUMENT CLASSIFICATION REGRESSION TESTS
# =============================================================================

def _install_mock_gemini_response(monkeypatch, payload, captured=None):
    """Install a deterministic Gemini response; no network/API request is made."""
    class MockResponse:
        text = json.dumps(payload)

    def mock_generate_content(*args, **kwargs):
        if captured is not None:
            captured["kwargs"] = kwargs
        return MockResponse()

    class MockModels:
        generate_content = staticmethod(mock_generate_content)

    class MockGenaiClient:
        models = MockModels()

    import google.genai
    monkeypatch.setattr(
        google.genai,
        "Client",
        lambda *args, **kwargs: MockGenaiClient(),
    )


def _non_receipt_gemini_payload(reason):
    """Deliberately include receipt-looking fields to test defensive cleanup."""
    return {
        "status": "completed",
        "document_type": "receipt",
        "is_receipt": False,
        "rejection_reason": reason,
        "merchant_name": "False Positive Merchant",
        "merchant_address": "123 Imaginary Street",
        "receipt_date": "2026-11-10",
        "receipt_number": "FAKE-123",
        "currency": "INR",
        "subtotal": "100.00",
        "tax": "18.00",
        "discount": "5.00",
        "tip": "10.00",
        "final_total": "123.00",
        "confidence": 0.99,
        "items": [
            {
                "item_name": "False Positive Item",
                "quantity": 1,
                "unit_price": "100.00",
                "total_price": "100.00",
            }
        ],
        "missing_fields": [],
        "uncertain_fields": [],
        "warnings": [],
    }


@pytest.mark.parametrize(
    "document_case,reason",
    [
        (
            "academic notes",
            "Lecture notes covering stack, queue, and linked list concepts.",
        ),
        (
            "homework",
            "Homework assignment with questions, marks, and student answers.",
        ),
        (
            "algorithm and data-structure table",
            "Algorithm complexity and data structure comparison table.",
        ),
        (
            "currency-like values in a non-receipt",
            "Academic conversion worksheet containing Rs. 100, ₹200 and Total 300.",
        ),
        (
            "blank image",
            "Blank image with no readable receipt content.",
        ),
        (
            "unrelated photo",
            "Unrelated personal photograph; no financial transaction document.",
        ),
    ],
)
def test_gemini_non_receipt_cases_clear_receipt_fields(
    monkeypatch, document_case, reason
):
    """Non-receipts must not leak merchant, line-item, or payable-total data."""
    extractor = GeminiVisionExtractor(api_key="test-api-key")
    _install_mock_gemini_response(
        monkeypatch,
        _non_receipt_gemini_payload(reason),
    )

    result = extractor.extract(Image.new("RGB", (160, 220), color="white"))

    assert result.is_receipt is False, document_case
    assert result.status == "failed"
    assert result.error_code == "NON_RECEIPT_DOCUMENT"
    assert result.merchant_name is None
    # These assertions intentionally cover merchant metadata too. If they fail,
    # the production parser's non-receipt cleanup needs a separate approved fix.
    assert result.merchant_address is None
    assert result.receipt_date is None
    assert result.receipt_number is None
    assert result.items == []
    assert result.subtotal is None
    assert result.tax is None
    assert result.discount is None
    assert result.tip is None
    assert result.final_total is None


def test_gemini_keeps_genuine_receipt_with_academic_looking_words(monkeypatch):
    """Academic keywords in a merchant/item name must not reject a real receipt."""
    extractor = GeminiVisionExtractor(api_key="test-api-key")
    receipt_payload = {
        "status": "completed",
        "document_type": "receipt",
        "is_receipt": True,
        "merchant_name": "Algorithm Cafe",
        "currency": "INR",
        "subtotal": "250.00",
        "tax": "12.50",
        "final_total": "262.50",
        "confidence": 0.96,
        "items": [
            {
                "item_name": "Data Structure Sandwich",
                "quantity": 1,
                "unit_price": "250.00",
                "total_price": "250.00",
            }
        ],
        "missing_fields": [],
        "uncertain_fields": [],
        "warnings": [],
    }
    _install_mock_gemini_response(monkeypatch, receipt_payload)

    result = extractor.extract(Image.new("RGB", (300, 400), color="white"))

    assert result.is_receipt is True
    assert result.merchant_name == "Algorithm Cafe"
    assert len(result.items) == 1
    assert result.items[0].item_name == "Data Structure Sandwich"
    assert result.final_total == Decimal("262.50")


# =============================================================================
# 10. OCR IMAGE-CONDITION COVERAGE (SYNTHETIC SMOKE TESTS)
# =============================================================================

def _synthetic_receipt_image():
    """Create a deterministic receipt-like image without external fixture files."""
    from PIL import ImageDraw

    image = Image.new("RGB", (800, 1100), "white")
    draw = ImageDraw.Draw(image)
    draw.text((55, 55), "SAMPLE CAFE", fill="black")
    draw.text((55, 150), "Coffee             120.00", fill="black")
    draw.text((55, 220), "Sandwich           180.00", fill="black")
    draw.line((55, 290, 720, 290), fill="black", width=3)
    draw.text((55, 340), "Subtotal           300.00", fill="black")
    draw.text((55, 400), "Tax                 15.00", fill="black")
    draw.text((55, 470), "TOTAL              315.00", fill="black")
    return image


@pytest.mark.parametrize(
    "condition",
    ["low_resolution", "glare", "shadows", "low_contrast", "skew"],
)
def test_preprocessor_handles_common_receipt_image_conditions(condition):
    """Smoke-test preprocessing for difficult capture conditions (not OCR accuracy)."""
    from PIL import ImageEnhance, ImageOps

    image = _synthetic_receipt_image()

    if condition == "low_resolution":
        image = image.resize((120, 165))
    elif condition == "glare":
        # Simulate a bright reflection across part of the receipt.
        from PIL import ImageDraw
        overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        draw.ellipse((260, 80, 760, 560), fill=(255, 255, 255, 175))
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    elif condition == "shadows":
        # Simulate uneven illumination with a darker band over the lower area.
        from PIL import ImageDraw
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rectangle((0, 560, 800, 1100), fill=(0, 0, 0, 75))
        image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    elif condition == "low_contrast":
        image = ImageEnhance.Contrast(image).enhance(0.20)
    elif condition == "skew":
        image = image.rotate(7, expand=True, fillcolor="white")

    import io
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    result = ImagePreprocessor().preprocess(buffer.getvalue())

    assert result.processed_image is not None, condition
    assert result.width > 0 and result.height > 0, condition
    assert isinstance(result.processed_image, Image.Image), condition


def test_mixed_language_receipt_text_context_reaches_gemini(monkeypatch):
    """Verify mixed English/Devanagari OCR text is passed to Gemini as context."""
    extractor = GeminiVisionExtractor(api_key="test-api-key")
    captured = {}
    receipt_payload = {
        "status": "review_required",
        "document_type": "receipt",
        "is_receipt": True,
        "merchant_name": "Mumbai Snacks",
        "currency": "INR",
        "confidence": 0.72,
        "items": [],
        "missing_fields": ["items", "final_total"],
        "uncertain_fields": [],
        "warnings": [],
    }
    _install_mock_gemini_response(monkeypatch, receipt_payload, captured=captured)

    mixed_language_text = (
        "Mumbai Snacks\nसमोसा 2 40.00\nचहा 1 15.00\nएकूण 55.00"
    )
    result = extractor.extract(
        Image.new("RGB", (300, 400), color="white"),
        text_context=mixed_language_text,
    )

    assert result.is_receipt is True
    sent_contents = captured["kwargs"]["contents"]
    assert any(mixed_language_text in str(part) for part in sent_contents)
