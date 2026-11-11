"""Receipt endpoints: upload, retrieve, stream image, trigger AI extraction, and edit items."""

from decimal import Decimal
import hmac
import logging
import os
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.models import ExtractionStatus, Receipt, ReceiptItem
from app.schemas.schemas import (
    ReceiptExtractionRequest,
    ReceiptItemsUpdateRequest,
    ReceiptResponse,
)
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
        original_filename=file.filename or safe_name,
        stored_file_path=stored_path,
        extraction_status=ExtractionStatus.PENDING,
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)

    if auto_extract:
        receipt = _extract_and_populate_receipt(receipt, db)

    return receipt


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
    "/{receipt_id}/extract",
    response_model=ReceiptResponse,
    summary="Trigger AI extraction on an uploaded receipt",
)
def extract_receipt(receipt_id: uuid.UUID, db: Session = Depends(get_db)):
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found.")
    return _extract_and_populate_receipt(receipt, db)


@router.get(
    "/{receipt_id}",
    response_model=ReceiptResponse,
    summary="Get receipt details including extracted items",
)
def get_receipt(receipt_id: uuid.UUID, db: Session = Depends(get_db)):
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found.")
    return receipt


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
    return receipt


@router.post(
    "/{receipt_id}/extraction",
    response_model=ReceiptResponse,
    summary="Submit AI extraction results for a receipt (used by Pawan's service)",
)
def submit_extraction(
    receipt_id: uuid.UUID,
    body: ReceiptExtractionRequest,
    db: Session = Depends(get_db),
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
    receipt.extraction_status = ExtractionStatus.COMPLETED

    # Delete any prior items and insert fresh
    for old_item in list(receipt.items):
        db.delete(old_item)

    for item_data in body.items:
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
