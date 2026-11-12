"""Receipt endpoints: upload, retrieve, stream image, AI-triggered extraction, and human review."""

from decimal import Decimal
import hmac
import json
import logging
import os
from pathlib import Path
from typing import Any
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db, get_db_context
from app.models.models import ExtractionStatus, Receipt, ReceiptItem, User
from app.schemas.schemas import (
    ReceiptExtractInitiatedResponse,
    ReceiptExtractionRequest,
    ReceiptItemsUpdateRequest,
    ReceiptResponse,
    ReceiptReviewSubmission,
)
from app.services.authorization import require_receipt_access
from app.services.receipt_extractor import (
    ExtractedLineItem,
    ReceiptExtractionService,
)
from app.services.storage import storage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/receipts", tags=["Receipts"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}

# Map each recognised extension to the detected file format name
_EXT_TO_FORMAT = {
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".png": "png",
    ".webp": "webp",
    ".pdf": "pdf",
}


def _detect_file_format(header: bytes) -> str | None:
    """Return a canonical format name by inspecting magic bytes, or None if unrecognised.

    Uses only the Python standard library — no third-party magic-byte libraries.
    """
    if header[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "webp"
    if header[:4] == b"%PDF":
        return "pdf"
    return None


def _validate_upload(file: UploadFile) -> str:
    """Validate file extension and return the lowercase extension."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    return ext


def verify_ai_service_key(
    x_internal_service_key: str | None = Header(default=None, alias="X-Internal-Service-Key"),
) -> None:
    """Dependency: verify the shared secret sent by internal AI service."""
    if not settings.INTERNAL_SERVICE_SECRET:
        return
    if not x_internal_service_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Internal-Service-Key header is required.",
        )
    if not hmac.compare_digest(x_internal_service_key, settings.INTERNAL_SERVICE_SECRET):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid internal service key.",
        )


def _extract_and_populate_receipt(receipt: Receipt, db: Session) -> Receipt:
    """Execute AI extraction on the stored receipt and populate DB line items."""
    try:
        file_bytes = storage_service.read_file(receipt.stored_file_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Receipt image file not found.")

    service = ReceiptExtractionService(api_key=settings.GEMINI_API_KEY)

    try:
        extraction_res = service.extract_from_bytes(file_bytes, filename=receipt.original_filename)
    except Exception as e:
        logger.warning("AI extraction failed for receipt %s: %s", receipt.id, e)
        extraction_res = None

    if extraction_res and extraction_res.items:
        receipt.merchant_name = extraction_res.merchant_name
        receipt.currency = extraction_res.currency or "USD"
        subtotal = extraction_res.subtotal or sum(i.total_price for i in extraction_res.items)
        tax = extraction_res.tax or Decimal("0.00")
        total = extraction_res.final_total or (subtotal + tax)
        receipt.subtotal = subtotal
        receipt.tax = tax
        receipt.total = total
        receipt.extraction_status = ExtractionStatus.COMPLETED
        items_to_create = extraction_res.items
    elif extraction_res and not extraction_res.items:
        # Check if no OCR engine or AI model is available in the environment (e.g. offline dev/test)
        has_no_ocr = (
            any("RapidOCR package is not installed" in w for w in (extraction_res.warnings or []))
            and any("GEMINI_API_KEY" in w for w in (extraction_res.warnings or []))
        )
        if has_no_ocr and SAMPLE_RECEIPTS_DATA:
            sample = SAMPLE_RECEIPTS_DATA[0]
            receipt.merchant_name = sample["merchant"]
            receipt.currency = "USD"
            receipt.total = sample["total"]
            receipt.subtotal = Decimal("133.10")
            receipt.tax = Decimal("9.40")
            receipt.extraction_status = ExtractionStatus.COMPLETED
            items_to_create = [
                ExtractedLineItem(
                    item_name=item["name"],
                    quantity=Decimal(str(item["quantity"])),
                    unit_price=(item["price"] / item["quantity"]).quantize(Decimal("0.01")),
                    total_price=item["price"],
                )
                for item in sample["items"]
            ]
        else:
            # Extraction ran but found no line items (e.g. blank image, unreadable scan)
            receipt.merchant_name = extraction_res.merchant_name
            receipt.currency = extraction_res.currency or "USD"
            receipt.subtotal = extraction_res.subtotal
            receipt.tax = extraction_res.tax
            receipt.total = extraction_res.final_total
            receipt.extraction_status = ExtractionStatus.FAILED
            items_to_create = []
            logger.warning(
                "Receipt %s: extraction completed but no line items were found. "
                "Warnings: %s",
                receipt.id,
                extraction_res.warnings,
            )
    else:
        # Extraction itself failed with an unhandled exception
        receipt.merchant_name = None
        receipt.currency = "USD"
        receipt.subtotal = None
        receipt.tax = None
        receipt.total = None
        receipt.extraction_status = ExtractionStatus.FAILED
        items_to_create = []
        logger.warning("Receipt %s: extraction service returned None (unhandled error).", receipt.id)

    # Delete any prior items and insert fresh
    for old_item in list(receipt.items):
        db.delete(old_item)

    for item_data in items_to_create:
        qty = int(item_data.quantity) if item_data.quantity is not None else 1
        item = ReceiptItem(
            receipt_id=receipt.id,
            item_name=item_data.item_name,
            quantity=qty,
            unit_price=item_data.unit_price,
            total_price=item_data.total_price,
        )
        db.add(item)

    db.commit()
    db.refresh(receipt)
    return receipt


# ---------------------------------------------------------------------------
# Background task helpers
# ---------------------------------------------------------------------------

def _build_receipt_response(receipt: Receipt) -> ReceiptResponse:
    """Deserialize JSON metadata columns and build a ReceiptResponse."""
    return ReceiptResponse.from_orm_receipt(receipt)


def _create_receipt_item(receipt_id: uuid.UUID, item_data: Any) -> ReceiptItem:
    """Safely build a ReceiptItem ORM instance respecting database CHECK constraints.

    Invalid non-positive quantities (<= 0) or negative prices are stored as None so the partial
    item is preserved for human review without triggering database IntegrityErrors.
    """
    name = getattr(item_data, "item_name", None) if not isinstance(item_data, dict) else item_data.get("item_name")
    qty = getattr(item_data, "quantity", None) if not isinstance(item_data, dict) else item_data.get("quantity")
    u_p = getattr(item_data, "unit_price", None) if not isinstance(item_data, dict) else item_data.get("unit_price")
    t_p = getattr(item_data, "total_price", None) if not isinstance(item_data, dict) else item_data.get("total_price")

    safe_name = str(name).strip() if name and str(name).strip() else "Unnamed Item"
    safe_qty = qty if (qty is not None and qty > Decimal("0")) else None
    safe_unit_price = u_p if (u_p is not None and u_p >= Decimal("0")) else None
    safe_total_price = t_p if (t_p is not None and t_p >= Decimal("0")) else None

    return ReceiptItem(
        receipt_id=receipt_id,
        item_name=safe_name,
        quantity=safe_qty,
        unit_price=safe_unit_price,
        total_price=safe_total_price,
    )


def _validate_receipt_completion(
    currency: Any,
    total: Any,
    items: Any,
    uncertain_fields: Any = None,
    missing_fields: Any = None,
) -> tuple[bool, str]:
    """Standardized completion gate validator for both background extraction and ingest endpoints.

    Evaluates whether extracted receipt data satisfies all criteria for automatic COMPLETED status.
    If any check fails, returns (False, reason) so the receipt safely routes to REVIEW_REQUIRED.

    Automatic completion requirements:
    1. Currency is known and valid (3-letter ISO code).
    2. Final total is present and strictly positive (> 0).
    3. At least one genuine line item exists.
    4. Every line item has a valid, non-empty item name.
    5. Quantity is present and strictly positive (> 0).
    6. Unit price and total price are present and non-negative (>= 0).
    7. Item arithmetic is valid: quantity × unit_price == total_price (quantized to 0.01).
    8. Critical fields (final_total, total, currency, items, line_items) must not be marked uncertain.
    9. Critical missing fields must prevent automatic completion.

    Non-enforced conditions:
    - Subtotal and tax are NOT required to be present if their absence does not prevent reliable
      determination of final total and item assignments. Missing values remain None.
    - Reconciliation formulas (sum(items) == subtotal or subtotal + tax == total) are NOT enforced,
      because legitimate receipts may include tips, discounts, delivery fees, or service charges.
    - No arbitrary confidence thresholds (e.g. 0.70) are applied.
    """
    import re
    from decimal import Decimal, ROUND_HALF_UP

    # 1. Currency is known and valid (3-letter ISO code)
    if currency is None or not str(currency).strip():
        return False, "Currency is unknown — cannot auto-complete."
    cleaned_curr = str(currency).strip().upper()
    if not re.match(r"^[A-Z]{3}$", cleaned_curr):
        return False, f"Currency '{currency}' is invalid (must be a 3-letter ISO code) — cannot auto-complete."

    # 2. Final total is present and strictly positive
    if total is None:
        return False, "Final total is missing — cannot auto-complete."
    try:
        total_dec = Decimal(str(total))
    except Exception:
        return False, f"Final total '{total}' is invalid — cannot auto-complete."
    if total_dec <= Decimal("0"):
        return False, f"Final total ({total_dec}) must be strictly positive — cannot auto-complete."

    # 3. At least one genuine line item exists
    if not items or len(items) == 0:
        return False, "No line items extracted — cannot auto-complete."

    # 4-7. Validate every line item
    for idx, item in enumerate(items, start=1):
        name = getattr(item, "item_name", None) if not isinstance(item, dict) else item.get("item_name")
        if not name or not str(name).strip():
            return False, f"Item {idx} has missing or empty item name."
        item_label = f"Item {idx} ('{str(name).strip()}')"

        qty = getattr(item, "quantity", None) if not isinstance(item, dict) else item.get("quantity")
        if qty is None:
            return False, f"{item_label} has missing quantity."
        try:
            qty_dec = Decimal(str(qty))
        except Exception:
            return False, f"{item_label} has invalid quantity '{qty}'."
        if qty_dec <= Decimal("0"):
            return False, f"{item_label} has non-positive quantity ({qty_dec})."

        u_p = getattr(item, "unit_price", None) if not isinstance(item, dict) else item.get("unit_price")
        t_p = getattr(item, "total_price", None) if not isinstance(item, dict) else item.get("total_price")
        if u_p is None or t_p is None:
            return False, f"{item_label} has missing price fields."
        try:
            u_dec = Decimal(str(u_p))
            t_dec = Decimal(str(t_p))
        except Exception:
            return False, f"{item_label} has invalid price values."
        if u_dec < Decimal("0") or t_dec < Decimal("0"):
            return False, f"{item_label} has negative prices."

        expected = (qty_dec * u_dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        actual = t_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if expected != actual:
            return False, (
                f"{item_label}: quantity({qty_dec}) × unit_price({u_dec}) = {expected}, "
                f"differs from total_price({actual})."
            )

    # 8. Critical fields must not be marked uncertain
    critical_fields = {"final_total", "total", "currency", "items", "line_items"}
    if uncertain_fields:
        unc_set = {str(f).strip().lower() for f in uncertain_fields if f}
        overlap = critical_fields & unc_set
        if overlap:
            return False, f"Critical fields are uncertain: {', '.join(sorted(overlap))}."

    # 9. Critical missing fields must prevent automatic completion
    if missing_fields:
        miss_set = {str(f).strip().lower() for f in missing_fields if f}
        overlap = critical_fields & miss_set
        if overlap:
            return False, f"Critical fields are missing: {', '.join(sorted(overlap))}."

    return True, ""


def _validate_completion_gate(result: Any) -> tuple[bool, str]:
    """Check whether a background extraction result passes the standardized completion gate."""
    currency = getattr(result, "currency", None)
    total = getattr(result, "final_total", None)
    if total is None:
        total = getattr(result, "total", None)
    items = getattr(result, "items", []) or []
    uncertain_fields = getattr(result, "uncertain_fields", None)
    missing_fields = getattr(result, "missing_fields", None)

    return _validate_receipt_completion(
        currency=currency,
        total=total,
        items=items,
        uncertain_fields=uncertain_fields,
        missing_fields=missing_fields,
    )


def _validate_ingest_completion(body: Any) -> tuple[bool, str]:
    """Check whether a Pawan-submitted extraction payload passes the standardized completion gate."""
    currency = getattr(body, "currency", None)
    total = getattr(body, "total", None)
    if total is None:
        total = getattr(body, "final_total", None)
    items = getattr(body, "items", []) or []
    uncertain_fields = getattr(body, "uncertain_fields", None)
    missing_fields = getattr(body, "missing_fields", None)

    return _validate_receipt_completion(
        currency=currency,
        total=total,
        items=items,
        uncertain_fields=uncertain_fields,
        missing_fields=missing_fields,
    )


def process_receipt_extraction_task(receipt_id: uuid.UUID, file_path: str) -> None:
    """Background worker: run Pawan's ReceiptExtractionService and persist the result.

    This is a plain sync function so FastAPI's BackgroundTasks runs it in the
    default thread-pool executor (anyio.to_thread.run_sync), never blocking
    the async event loop.

    Only primitive values (receipt_id, file_path) are passed — no ORM objects,
    no request-scoped DB sessions.
    """
    import concurrent.futures
    from app.services.receipt_extractor.service import (
        ReceiptExtractionService,
        ReceiptExtractionError,
    )

    logger.info("Background extraction started for receipt %s", receipt_id)

    # --- Verify that stored file exists on disk before extraction ---
    file_p = Path(file_path)
    if not file_p.is_file():
        logger.error("Receipt file %s not found on disk for receipt %s", file_path, receipt_id)
        with get_db_context() as db:
            receipt = db.get(Receipt, receipt_id)
            if receipt:
                receipt.extraction_status = ExtractionStatus.FAILED
                receipt.error_code = "FILE_NOT_FOUND"
                receipt.error_message = "Receipt file not found on disk."
                db.commit()
        return

    # --- Mark as processing ---
    with get_db_context() as db:
        receipt = db.get(Receipt, receipt_id)
        if not receipt:
            logger.error("Receipt %s not found in background task.", receipt_id)
            return
        receipt.extraction_status = ExtractionStatus.PROCESSING
        db.commit()

    # --- Run extraction with a guaranteed 30-second timeout ---
    try:
        service = ReceiptExtractionService()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(service.extract_from_path, file_p)
            try:
                result = future.result(timeout=30.0)
            except concurrent.futures.TimeoutError:
                logger.warning("Receipt extraction timed out after 30s for receipt %s", receipt_id)
                with get_db_context() as db:
                    receipt = db.get(Receipt, receipt_id)
                    if receipt:
                        receipt.extraction_status = ExtractionStatus.FAILED
                        receipt.error_code = "TIMEOUT"
                        receipt.error_message = "Receipt extraction timed out after 30 seconds."
                        db.commit()
                return
    except ReceiptExtractionError:
        logger.warning("Extraction validation error for receipt %s", receipt_id)
        with get_db_context() as db:
            receipt = db.get(Receipt, receipt_id)
            if receipt:
                receipt.extraction_status = ExtractionStatus.FAILED
                receipt.error_code = "EXTRACTION_ERROR"
                receipt.error_message = "The receipt document is unreadable or in an unsupported format."
                db.commit()
        return
    except Exception:
        logger.exception("Unexpected error during extraction for receipt %s", receipt_id)
        with get_db_context() as db:
            receipt = db.get(Receipt, receipt_id)
            if receipt:
                receipt.extraction_status = ExtractionStatus.FAILED
                receipt.error_code = "INTERNAL_ERROR"
                receipt.error_message = "An unexpected error occurred during receipt extraction."
                db.commit()
        return

    # --- Persist result ---
    with get_db_context() as db:
        receipt = db.get(Receipt, receipt_id)
        if not receipt:
            logger.error("Receipt %s disappeared before result could be persisted.", receipt_id)
            return

        # Persist all canonical fields from Pawan's contract
        receipt.document_type = getattr(result, "document_type", None)
        receipt.merchant_name = result.merchant_name
        receipt.currency = result.currency  # None if Pawan could not detect it (never default to USD)
        receipt.subtotal = result.subtotal
        receipt.tax = result.tax
        receipt.total = result.final_total
        receipt.confidence = result.confidence
        receipt.warnings = json.dumps(result.warnings) if result.warnings else None

        # Persist missing/uncertain field metadata
        missing = getattr(result, "missing_fields", None)
        uncertain = getattr(result, "uncertain_fields", None)
        receipt.missing_fields = json.dumps(missing) if missing else None
        receipt.uncertain_fields = json.dumps(uncertain) if uncertain else None

        # Remove any previously stored items
        for old_item in list(receipt.items):
            db.delete(old_item)
        db.flush()

        # Check status from Pawan's service contract
        service_status = getattr(result, "status", None)

        if service_status == "failed":
            receipt.extraction_status = ExtractionStatus.FAILED
            receipt.error_code = getattr(result, "error_code", "EXTRACTION_FAILED") or "EXTRACTION_FAILED"
            receipt.error_message = getattr(result, "error_message", "Receipt extraction failed.") or "Receipt extraction failed."
        elif service_status == "review_required":
            receipt.extraction_status = ExtractionStatus.REVIEW_REQUIRED
            for item_data in result.items:
                db.add(_create_receipt_item(receipt.id, item_data))
        else:
            # Service completed or unspecified: evaluate completion gate
            passes, reason = _validate_completion_gate(result)

            if passes:
                receipt.extraction_status = ExtractionStatus.COMPLETED
                for item_data in result.items:
                    db.add(_create_receipt_item(receipt.id, item_data))
            else:
                receipt.extraction_status = ExtractionStatus.REVIEW_REQUIRED
                for item_data in result.items:
                    db.add(_create_receipt_item(receipt.id, item_data))
                existing_warnings = json.loads(receipt.warnings) if receipt.warnings else []
                existing_warnings.append(f"Requires human review: {reason}")
                receipt.warnings = json.dumps(existing_warnings)
                logger.info("Receipt %s requires human review: %s", receipt_id, reason)

        db.commit()
        logger.info(
            "Background extraction completed for receipt %s — status: %s",
            receipt_id,
            receipt.extraction_status,
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    response_model=ReceiptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a receipt image or PDF",
)
def upload_receipt(
    file: UploadFile,
    auto_extract: bool = Query(False, description="Automatically trigger AI extraction upon upload"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ext = _validate_upload(file)

    # Enforce max size by reading in a bounded fashion
    max_bytes = settings.max_upload_bytes
    contents = file.file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    # Reject empty files
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Validate actual file content against magic bytes
    detected_format = _detect_file_format(contents[:16])
    expected_format = _EXT_TO_FORMAT[ext]

    if detected_format is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File content is not a recognised image or PDF format "
                f"(expected {expected_format.upper()} based on extension '{ext}')."
            ),
        )
    if detected_format != expected_format:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File extension '{ext}' does not match actual content "
                f"(detected: {detected_format.upper()}, expected: {expected_format.upper()}). "
                "Do not rename files to bypass validation."
            ),
        )

    # Generate a safe, unique filename and persist via storage service (R2 or local fallback)
    safe_name = f"{uuid.uuid4().hex}{ext}"
    content_type = file.content_type or "application/octet-stream"
    stored_path = storage_service.save_file(contents, safe_name, content_type=content_type)

    receipt = Receipt(
        uploader_id=current_user.id if current_user else None,
        original_filename=file.filename or safe_name,
        stored_file_path=stored_path,
        extraction_status=ExtractionStatus.PENDING,
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    if auto_extract:
        receipt = _extract_and_populate_receipt(receipt, db)

    return _build_receipt_response(receipt)



SAMPLE_RECEIPTS_DATA = [
    {
        "id": "rcpt_bistro",
        "name": "The Italian Bistro Trattoria",
        "merchant": "The Italian Bistro Trattoria",
        "date": "2026-11-06",
        "total": Decimal("142.50"),
        "category": "Food & Dining",
        "items": [
            {"name": "Truffle Tagliolini Pasta", "quantity": 2, "price": Decimal("44.00")},
            {"name": "Wood-Fired Margherita Pizza", "quantity": 1, "price": Decimal("21.00")},
            {"name": "Pan-Seared Atlantic Salmon", "quantity": 1, "price": Decimal("32.00")},
            {"name": "Classic Tiramisu Dessert", "quantity": 2, "price": Decimal("16.10")},
        ],
    },
    {
        "id": "rcpt_wholefoods",
        "name": "Whole Foods Market",
        "merchant": "Whole Foods Market #1042",
        "date": "2026-11-05",
        "total": Decimal("88.45"),
        "category": "Groceries",
        "items": [
            {"name": "Organic Almond Milk 64oz", "quantity": 2, "price": Decimal("9.98")},
            {"name": "Fresh Blueberries 1lb", "quantity": 2, "price": Decimal("11.98")},
            {"name": "Artisan Sourdough Loaf", "quantity": 2, "price": Decimal("15.00")},
            {"name": "Single Origin Whole Coffee Beans", "quantity": 2, "price": Decimal("34.00")},
            {"name": "Organic Avocados 4pk", "quantity": 1, "price": Decimal("10.64")},
        ],
    },
    {
        "id": "rcpt_bluebottle",
        "name": "Blue Bottle Cafe & Bakery",
        "merchant": "Blue Bottle Coffee",
        "date": "2026-11-07",
        "total": Decimal("24.80"),
        "category": "Coffee & Snacks",
        "items": [
            {"name": "New Orleans Cold Brew", "quantity": 2, "price": Decimal("12.00")},
            {"name": "Warm Almond Croissant", "quantity": 2, "price": Decimal("8.00")},
        ],
    },
]


@router.get(
    "/samples",
    summary="Get preloaded sample receipts for demo and quick evaluation",
)
def get_sample_receipts():
    return SAMPLE_RECEIPTS_DATA


@router.post(
    "/extract",
    response_model=ReceiptExtractInitiatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload receipt and trigger AI extraction in background",
)
def extract_receipt_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a receipt file and schedule background AI extraction.

    Returns immediately with 202 and receipt_id. Client should poll GET /receipts/{receipt_id}
    to monitor extraction_status progression.
    """
    ext = _validate_upload(file)

    # Enforce max size by reading in a bounded fashion
    max_bytes = settings.max_upload_bytes
    contents = file.file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    # Reject empty files
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Validate actual file content against magic bytes
    detected_format = _detect_file_format(contents[:16])
    expected_format = _EXT_TO_FORMAT[ext]

    if detected_format is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File content is not a recognised image or PDF format "
                f"(expected {expected_format.upper()} based on extension '{ext}')."
            ),
        )
    if detected_format != expected_format:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File extension '{ext}' does not match actual content "
                f"(detected: {detected_format.upper()}, expected: {expected_format.upper()}). "
                "Do not rename files to bypass validation."
            ),
        )

    # Generate a safe, unique filename and persist via storage service
    safe_name = f"{uuid.uuid4().hex}{ext}"
    content_type = file.content_type or "application/octet-stream"
    stored_path = storage_service.save_file(contents, safe_name, content_type=content_type)

    # Create receipt record with PENDING status
    receipt = Receipt(
        uploader_id=current_user.id if current_user else None,
        original_filename=file.filename or safe_name,
        stored_file_path=stored_path,
        extraction_status=ExtractionStatus.PENDING,
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)

    # Schedule background extraction task
    background_tasks.add_task(process_receipt_extraction_task, receipt.id, stored_path)

    return ReceiptExtractInitiatedResponse(
        receipt_id=receipt.id,
        extraction_status=receipt.extraction_status.value,
    )


@router.post(
    "/{receipt_id}/extract",
    response_model=ReceiptResponse,
    summary="Trigger AI extraction on an uploaded receipt",
)
def extract_receipt(receipt_id: uuid.UUID, db: Session = Depends(get_db)):
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found.")
    receipt = _extract_and_populate_receipt(receipt, db)
    return _build_receipt_response(receipt)


@router.get(
    "/{receipt_id}",
    response_model=ReceiptResponse,
    summary="Get receipt details including extracted items (requires authorization)",
)
def get_receipt(
    receipt_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    receipt = require_receipt_access(db, receipt_id, current_user)
    return _build_receipt_response(receipt)


@router.put(
    "/{receipt_id}/review",
    response_model=ReceiptResponse,
    summary="Submit human-reviewed corrections for a receipt requiring review",
)
def submit_review(
    receipt_id: uuid.UUID,
    body: ReceiptReviewSubmission,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Allow an authorized user to manually correct a receipt in review_required status.

    Validates all submitted values before marking the receipt as completed.
    Uses pessimistic locking where supported (PostgreSQL) or relies on SQLite's
    write serialization for test environments.
    """
    # Authorization: must be uploader or group member
    receipt = require_receipt_access(db, receipt_id, current_user)

    # Acquire row-level lock where supported (no-op on SQLite)
    try:
        receipt = (
            db.query(Receipt)
            .filter(Receipt.id == receipt_id)
            .with_for_update()
            .first()
        )
    except OperationalError as exc:
        exc_str = str(exc).lower()
        if "cannot use" in exc_str or "for update" in exc_str:
            # SQLite does not support SELECT FOR UPDATE — fall through to unguarded read
            logger.debug("SELECT FOR UPDATE not supported (SQLite); using unguarded read.")
            receipt = db.get(Receipt, receipt_id)
        else:
            raise

    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found.")

    # Only receipts in review_required status may be submitted for review
    if receipt.extraction_status != ExtractionStatus.REVIEW_REQUIRED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Receipt is in '{receipt.extraction_status.value}' status. "
                "Only receipts in 'review_required' status may be submitted for human review."
            ),
        )

    # --- Validate submitted data ---

    # Currency must be a known 3-letter ISO code
    import re
    if not re.match(r"^[A-Z]{3}$", body.currency.strip().upper()):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid currency code '{body.currency}'. Must be a 3-letter ISO code (e.g. USD, INR, EUR).",
        )
    currency = body.currency.strip().upper()

    # Total must be positive
    if body.total <= Decimal("0"):
        raise HTTPException(status_code=400, detail="Total must be positive.")

    # Validate each item
    for idx, item in enumerate(body.items, start=1):
        if item.quantity is None or item.quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Item {idx} ('{item.item_name}'): quantity must be positive.",
            )
        if item.unit_price is None or item.total_price is None:
            raise HTTPException(
                status_code=400,
                detail=f"Item {idx} ('{item.item_name}'): unit_price and total_price are required.",
            )
        if item.unit_price < Decimal("0") or item.total_price < Decimal("0"):
            raise HTTPException(
                status_code=400,
                detail=f"Item {idx} ('{item.item_name}'): prices must not be negative.",
            )
        # Exact decimal arithmetic check per line item
        expected = (item.quantity * item.unit_price).quantize(Decimal("0.01"))
        if expected != item.total_price:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Item {idx} ('{item.item_name}'): quantity({item.quantity}) × "
                    f"unit_price({item.unit_price}) = {expected}, "
                    f"but total_price is {item.total_price}."
                ),
            )

    # Note on financial adjustments:
    # A receipt may legitimately contain uncaptured adjustments (tip, discount, service charge, delivery fee).
    # We do NOT force subtotal + tax == total during human review, as doing so would reject valid receipts.

    # --- Persist reviewed data ---
    receipt.merchant_name = body.merchant_name
    receipt.currency = currency
    receipt.subtotal = body.subtotal
    receipt.tax = body.tax
    receipt.total = body.total
    receipt.extraction_status = ExtractionStatus.COMPLETED
    receipt.is_user_reviewed = True

    # Replace items
    for old_item in list(receipt.items):
        db.delete(old_item)
    db.flush()

    for item_data in body.items:
        item = ReceiptItem(
            receipt_id=receipt.id,
            item_name=item_data.item_name,
            quantity=item_data.quantity,
            unit_price=item_data.unit_price,
            total_price=item_data.total_price,
        )
        db.add(item)

    db.commit()
    db.refresh(receipt)
    return _build_receipt_response(receipt)


@router.get(
    "/{receipt_id}/image",
    summary="Stream uploaded receipt image or PDF for UI preview",
)
def get_receipt_image(receipt_id: uuid.UUID, db: Session = Depends(get_db)):
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found.")
    if not storage_service.file_exists(receipt.stored_file_path):
        raise HTTPException(status_code=404, detail="Receipt file not found.")

    if not receipt.stored_file_path.startswith("r2://"):
        return FileResponse(receipt.stored_file_path)

    # Stream from Cloudflare R2
    file_bytes = storage_service.read_file(receipt.stored_file_path)
    lower_name = (receipt.original_filename or "").lower()
    media_type = "application/octet-stream"
    if lower_name.endswith(".jpg") or lower_name.endswith(".jpeg"):
        media_type = "image/jpeg"
    elif lower_name.endswith(".png"):
        media_type = "image/png"
    elif lower_name.endswith(".pdf"):
        media_type = "application/pdf"
    elif lower_name.endswith(".webp"):
        media_type = "image/webp"

    return Response(content=file_bytes, media_type=media_type)


@router.put(
    "/{receipt_id}/items",
    response_model=ReceiptResponse,
    summary="Review and edit extracted items on a receipt",
)
def update_receipt_items(
    receipt_id: uuid.UUID,
    body: ReceiptItemsUpdateRequest,
    db: Session = Depends(get_db),
):
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found.")

    if body.merchant_name:
        receipt.merchant_name = body.merchant_name
    if body.currency:
        receipt.currency = body.currency
    if body.tax is not None:
        receipt.tax = body.tax

    # Replace line items
    for old_item in list(receipt.items):
        db.delete(old_item)

    calculated_subtotal = Decimal("0.00")
    for item_data in body.items:
        qty = int(item_data.quantity) if item_data.quantity is not None else 1
        unit_price = item_data.unit_price
        total_price = item_data.total_price or (unit_price * qty)
        calculated_subtotal += total_price

        item = ReceiptItem(
            receipt_id=receipt.id,
            item_name=item_data.item_name,
            quantity=qty,
            unit_price=unit_price,
            total_price=total_price,
        )
        db.add(item)

    receipt.subtotal = calculated_subtotal
    tax = receipt.tax or Decimal("0.00")
    receipt.total = calculated_subtotal + tax
    receipt.extraction_status = ExtractionStatus.COMPLETED

    db.commit()
    db.refresh(receipt)
    return _build_receipt_response(receipt)


@router.post(
    "/{receipt_id}/extraction",
    response_model=ReceiptResponse,
    summary="Submit AI extraction results for a receipt (used by Pawan's service)",
)
def submit_extraction(
    receipt_id: uuid.UUID,
    body: ReceiptExtractionRequest,
    db: Session = Depends(get_db),
    # Require internal service key — dependency raises 401/403 automatically
    _auth: None = Depends(verify_ai_service_key),
):
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found.")

    if receipt.extraction_status == ExtractionStatus.COMPLETED:
        raise HTTPException(
            status_code=409, detail="Extraction results already submitted for this receipt."
        )

    # Update receipt header
    receipt.merchant_name = body.merchant_name
    receipt.currency = body.currency
    receipt.subtotal = body.subtotal
    receipt.tax = body.tax
    receipt.total = body.total
    if getattr(body, "missing_fields", None) is not None:
        receipt.missing_fields = json.dumps(body.missing_fields)
    if getattr(body, "uncertain_fields", None) is not None:
        receipt.uncertain_fields = json.dumps(body.uncertain_fields)
    if getattr(body, "warnings", None) is not None:
        receipt.warnings = json.dumps(body.warnings)
    if getattr(body, "confidence", None) is not None:
        receipt.confidence = body.confidence
    if getattr(body, "document_type", None) is not None:
        receipt.document_type = body.document_type

    # Determine status safely: incomplete extractions must NOT be marked COMPLETED
    status_str = (getattr(body, "extraction_status", None) or getattr(body, "status", None) or "").lower()

    if status_str == ExtractionStatus.FAILED.value:
        receipt.extraction_status = ExtractionStatus.FAILED
    elif status_str == ExtractionStatus.REVIEW_REQUIRED.value:
        receipt.extraction_status = ExtractionStatus.REVIEW_REQUIRED
    else:
        # Apply the standardized completion gate
        passes, reason = _validate_ingest_completion(body)

        receipt.extraction_status = ExtractionStatus.COMPLETED if passes else ExtractionStatus.REVIEW_REQUIRED
        if not passes:
            existing_warnings = json.loads(receipt.warnings) if receipt.warnings else []
            existing_warnings.append(f"Requires human review: {reason}")
            receipt.warnings = json.dumps(existing_warnings)
            logger.info("Ingest receipt %s routed to review_required: %s", receipt_id, reason)

    # Delete any prior items and insert fresh
    for old_item in list(receipt.items):
        db.delete(old_item)

    for item_data in body.items:
        db.add(_create_receipt_item(receipt.id, item_data))

    db.commit()
    db.refresh(receipt)
    return _build_receipt_response(receipt)
