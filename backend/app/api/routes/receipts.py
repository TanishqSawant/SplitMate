"""Receipt endpoints: upload, retrieve, and submit extraction results."""

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.models import Receipt, ReceiptItem, ExtractionStatus
from app.schemas.schemas import (
    ReceiptExtractionRequest,
    ReceiptResponse,
)

router = APIRouter(prefix="/api/receipts", tags=["Receipts"])

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


def _validate_upload(file: UploadFile) -> str:
    """Validate file type and return the lowercase extension."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required.")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    return ext


@router.post(
    "/upload",
    response_model=ReceiptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a receipt image or PDF",
)
def upload_receipt(file: UploadFile, db: Session = Depends(get_db)):
    ext = _validate_upload(file)

    # Enforce max size by reading in a bounded fashion
    max_bytes = settings.max_upload_bytes
    contents = file.file.read(max_bytes + 1)
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB} MB.",
        )

    # Generate a safe, unique filename
    safe_name = f"{uuid.uuid4().hex}{ext}"
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / safe_name

    with open(file_path, "wb") as f:
        f.write(contents)

    receipt = Receipt(
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
    summary="Get receipt details including extracted items",
)
def get_receipt(receipt_id: uuid.UUID, db: Session = Depends(get_db)):
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(status_code=404, detail="Receipt not found.")
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

