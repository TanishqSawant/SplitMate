# SplitMate AI Receipt Extraction Integration Guide

**Author:** Pawan (AI Receipt Extraction Lead)  
**Target Deadline:** November 13, 2026 (PayPal AI Hackathon)  
**Status:** Tested & Integration-Ready (100% test pass rate)

---

## 1. Overview

The AI Receipt Extraction module (`backend/app/services/receipt_extractor/`) provides automated computer vision OCR, document preprocessing, blur detection, deskewing, and multimodal structured extraction using Google Gemini Vision, with a deterministic fallback engine.

### Key Capabilities
- **Multi-Format Support**: JPG, JPEG, PNG, WEBP, and PDF documents.
- **Pure-Python PDF Rasterization**: Uses `pypdfium2` (zero external C++ dependencies like Poppler on Windows).
- **OpenCV Preprocessing**: Automatic Laplacian variance blur detection ($\sigma^2 < 85.0$), text deskewing, and adaptive contrast enhancement (CLAHE).
- **12 Canonical Extracted Fields**:
  1. `merchant_name`
  2. `merchant_address`
  3. `receipt_date`
  4. `receipt_number`
  5. `currency`
  6. `items` (`item_name`, `quantity`, `unit_price`, `total_price`)
  7. `subtotal`
  8. `tax` (GST / Sales Tax)
  9. `discount`
  10. `tip`
  11. `final_total`
  12. Quality metadata (`confidence`, `is_fallback`, `warnings`)
- **Strict Anti-Hallucination**: Fields default to `null` if not visible on the bill.
- **Mathematical Reconciliation**: Validates $\text{subtotal} + \text{tax} + \text{tip} - \text{discount} \approx \text{final\_total}$. Discrepancies generate warnings without breaking.
- **Dual Contract Adapters**: Built-in adapters for Tanishq's backend and Dhruv's frontend.

---

## 2. For Tanishq: Backend Routing Integration

To integrate the AI extractor into the existing FastAPI backend routes without breaking existing functionality, update `backend/app/api/routes/receipts.py`:

### Option A: Dedicated Direct Extraction Endpoint (Serves Dhruv's React UI)
In `frontend/src/api/endpoints.js`, Dhruv's frontend calls `POST /api/receipts/extract`:

```python
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.services.receipt_extractor import ReceiptExtractionService, ReceiptExtractionError

service = ReceiptExtractionService()

@router.post("/extract", summary="Direct AI receipt extraction for frontend review")
async def extract_receipt(file: UploadFile = File(...)):
    """Receives receipt file, processes with OpenCV and AI, and returns frontend-ready schema."""
    try:
        contents = await file.read()
        result = service.extract_from_bytes(contents, filename=file.filename or "receipt.jpg")
        return result.to_frontend_contract()
    except ReceiptExtractionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failure: {str(e)}")
```

### Option B: Automatic Extraction Upon Receipt Upload
In `POST /api/receipts/upload`, after saving the file to disk:

```python
# Run AI extraction
try:
    extraction = service.extract_from_bytes(contents, filename=file.filename)
    backend_payload = extraction.to_backend_contract()
    
    receipt.merchant_name = backend_payload["merchant_name"]
    receipt.currency = backend_payload["currency"]
    receipt.subtotal = Decimal(backend_payload["subtotal"])
    receipt.tax = Decimal(backend_payload["tax"])
    receipt.total = Decimal(backend_payload["total"])
    receipt.extraction_status = ExtractionStatus.COMPLETED
    
    for item_data in backend_payload["items"]:
        item = ReceiptItem(
            receipt_id=receipt.id,
            item_name=item_data["item_name"],
            quantity=item_data["quantity"],
            unit_price=Decimal(item_data["unit_price"]),
            total_price=Decimal(item_data["total_price"]),
        )
        db.add(item)
except Exception:
    receipt.extraction_status = ExtractionStatus.FAILED

db.commit()
db.refresh(receipt)
return receipt
```

---

## 3. For Dhruv: Frontend Data Contract

When calling the extraction endpoint, the AI module returns the following JSON payload, matching the exact format consumed by `ExtractionResult.jsx` and `ReceiptPreview.jsx`:

```json
{
  "merchant": "Mario's Italian Bistro",
  "merchant_name": "Mario's Italian Bistro",
  "merchant_address": "123 Little Italy Way, New York, NY 10013",
  "date": "2026-11-06",
  "receipt_number": "REC-2026-9481",
  "category": "Food & Dining",
  "currency": "USD",
  "subtotal": 58.50,
  "tax": 5.27,
  "tip": 10.00,
  "discount": 0.00,
  "total": 73.77,
  "confidence": 0.95,
  "is_fallback": false,
  "extraction_method": "gemini_vision",
  "warnings": [],
  "items": [
    {
      "id": "item_1",
      "name": "Margherita Pizza Large",
      "item_name": "Margherita Pizza Large",
      "quantity": 1,
      "price": 18.00,
      "unit_price": 18.00,
      "total_price": 18.00
    },
    {
      "id": "item_2",
      "name": "Fettuccine Alfredo",
      "item_name": "Fettuccine Alfredo",
      "quantity": 2,
      "price": 28.00,
      "unit_price": 14.00,
      "total_price": 28.00
    }
  ]
}
```

---

## 4. For Sunil: Testing & Demo Guide

### Running AI Module Tests
Activate the backend environment and run pytest:

```bash
cd backend
$env:PYTHONPATH="."
$env:DATABASE_URL="sqlite:///./test.db"
pytest tests/test_ai_extractor.py -v
```

### Test Fixtures Included
Located at `backend/tests/fixtures/receipts/`:
1. `receipt_01_clear_restaurant.png`: High-clarity multi-item dinner bill.
2. `receipt_02_blurry_takeout.png`: Out-of-focus capture. Verifies Laplacian variance blur detector flags warning.
3. `receipt_03_rotated_grocery.png`: Tilted capture. Verifies OpenCV deskewing.
4. `receipt_04_incomplete_cafe.png`: Cash receipt with no address or tax. Verifies null safety.
5. `receipt_05_digital_invoice.pdf`: Real PDF invoice. Verifies `pypdfium2` rasterization.

### Live Gemini Vision Configuration
Set `GEMINI_API_KEY` in `backend/.env`:
```env
GEMINI_API_KEY=your_google_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
```
*(If omitted, the module operates in offline fallback mode with `is_fallback=True` and all unit tests pass).*

