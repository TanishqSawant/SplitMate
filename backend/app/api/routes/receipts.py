"""Receipt endpoints: upload, retrieve, and submit extraction results."""

import hmac
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.models import ExtractionStatus, Receipt, ReceiptItem, User
from app.schemas.schemas import (
    ReceiptExtractionRequest,
    ReceiptResponse,
)
from app.services.authorization import require_receipt_access

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
    """Dependency: verify the shared secret sent by Pawan's AI service.

    Returns HTTP 401 if the header is absent, HTTP 403 if the value is wrong.
    The secret is compared with hmac.compare_digest to avoid timing attacks.
    The secret value is never echoed back in a response or log message.
    """
    if not x_internal_service_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Internal-Service-Key header is required.",
        )
    expected = settings.INTERNAL_SERVICE_SECRET
    # Both values must be non-empty for a meaningful comparison
    if not expected or not hmac.compare_digest(x_internal_service_key, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid internal service key.",
        )


@router.post(
    "/upload",
    response_model=ReceiptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a receipt image or PDF",
)
def upload_receipt(
    file: UploadFile,
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

    # Fix 2: Validate actual file content against magic bytes
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

    # Generate a safe, unique filename — never use the client-supplied name
    safe_name = f"{uuid.uuid4().hex}{ext}"
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / safe_name

    with open(file_path, "wb") as f:
        f.write(contents)

    receipt = Receipt(
        uploader_id=current_user.id,
        original_filename=file.filename,
        stored_file_path=str(file_path),
        extraction_status=ExtractionStatus.PENDING,
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


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
    # Fix 3: Require internal service key — dependency raises 401/403 automatically
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
    for old_item in receipt.items:
        db.delete(old_item)

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
    return receipt

