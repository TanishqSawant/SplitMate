"""Pydantic schemas and contract adapters for AI Receipt Extraction.

Defines the canonical extraction schema adhering to all 12 requested fields:
- Merchant name
- Merchant address
- Receipt date
- Receipt number
- Currency
- Item names, quantities, unit prices, total prices
- Subtotal
- GST / Tax
- Discount
- Final total

Includes adapters to:
1. Tanishq's backend schema (ReceiptExtractionRequest)
2. Dhruv's frontend schema (ExtractionResult / ExpenseContext)
"""

from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any
from pydantic import BaseModel, Field, field_validator, model_validator


def _quantize_decimal(value: Decimal | float | int | str | None) -> Decimal | None:
    """Helper to cleanly round and quantize to 2 decimal places."""
    if value is None:
        return None
    try:
        dec = Decimal(str(value))
        return dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return None


class ExtractedLineItem(BaseModel):
    """Line item extracted from receipt.
    
    Adheres to the strict rule: Missing quantity or price must remain null, never invented.
    """
    item_name: str = Field(..., min_length=1, max_length=255, description="Name or description of line item")
    quantity: int | None = Field(default=None, ge=1, description="Quantity purchased or null if missing")
    unit_price: Decimal | None = Field(default=None, ge=0, description="Unit price per item or null if missing")
    total_price: Decimal | None = Field(default=None, ge=0, description="Total price for line item or null if missing")

    @field_validator("unit_price", "total_price", mode="before")
    @classmethod
    def round_prices(cls, v: Any) -> Decimal | None:
        if v is None or v == "":
            return None
        return _quantize_decimal(v)

    @model_validator(mode="after")
    def reconcile_item_total(self) -> "ExtractedLineItem":
        # Only derive when both components exist; never invent missing values
        if self.total_price is None and self.unit_price is not None and self.quantity is not None:
            self.total_price = (self.unit_price * self.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif self.unit_price is None and self.total_price is not None and self.quantity is not None and self.quantity > 0:
            self.unit_price = (self.total_price / self.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return self

    def to_dict(self) -> dict[str, Any]:
        """Serializes line item with decimal strings for monetary values."""
        return {
            "item_name": self.item_name,
            "quantity": self.quantity,
            "unit_price": str(self.unit_price) if self.unit_price is not None else None,
            "total_price": str(self.total_price) if self.total_price is not None else None,
        }


class ReceiptExtractionResult(BaseModel):
    """Canonical structured receipt extraction output containing all 12 required fields.
    
    Adheres strictly to the rule: Never hallucinate missing receipt information. Use null where unavailable.
    """
    # 0. Document Classification & Validation Status
    status: str = Field(default="completed", description="AI extraction status: 'completed', 'review_required', or 'failed'")
    document_type: str | None = Field(default="receipt", description="Document type: 'receipt', 'invoice', 'non_receipt', or null")
    is_receipt: bool = Field(default=True, description="True if document is a valid financial receipt/invoice, False if non-receipt, academic, or rejected")
    rejection_reason: str | None = Field(default=None, description="Detailed explanation if document was rejected as non-receipt")
    error_code: str | None = Field(default=None, description="Error code on failure: NON_RECEIPT_DOCUMENT, TIMEOUT, AI_EXTRACTION_FAILED, etc.")
    error_message: str | None = Field(default=None, description="Human-readable error explanation on failure")

    # 1. Merchant Details
    merchant_name: str | None = Field(default=None, description="Name of merchant/vendor or null")
    merchant_address: str | None = Field(default=None, description="Physical address or location or null")

    # 2. Receipt Identifiers & Date
    receipt_date: str | None = Field(default=None, description="Receipt date in YYYY-MM-DD format if known, else raw string or null")
    receipt_number: str | None = Field(default=None, description="Invoice/receipt/bill number or null")

    # 3. Currency
    currency: str | None = Field(default=None, description="3-letter ISO currency code (USD, EUR, INR, GBP, etc.) or null if missing")

    # 4. Itemized Line Items
    items: list[ExtractedLineItem] = Field(default_factory=list, description="Extracted line items")

    # 5. Financial Totals (Preserved as Python Decimal internally)
    subtotal: Decimal | None = Field(default=None, ge=0, description="Subtotal before taxes and discounts, or null")
    tax: Decimal | None = Field(default=None, ge=0, description="GST / VAT / Sales tax amount, or null")
    discount: Decimal | None = Field(default=None, ge=0, description="Discounts or coupons applied, or null")
    tip: Decimal | None = Field(default=None, ge=0, description="Gratuity or tip, or null")
    final_total: Decimal | None = Field(default=None, ge=0, description="Final payable amount, or null")

    # 6. Extraction Quality Metadata & Review Fields
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Overall confidence score (0.0 to 1.0)")
    missing_fields: list[str] = Field(default_factory=list, description="Fields genuinely missing from receipt")
    uncertain_fields: list[str] = Field(default_factory=list, description="Fields with math discrepancies or low legibility")
    warnings: list[str] = Field(default_factory=list, description="Quality warnings, blur notices, or missing field diagnostics")
    is_fallback: bool = Field(default=False, description="True if heuristic/regex fallback was used instead of primary AI model")
    extraction_method: str = Field(default="gemini_vision", description="Method name: gemini_vision or regex_heuristic_fallback")

    @field_validator("currency", mode="before")
    @classmethod
    def clean_currency(cls, v: Any) -> str | None:
        if v is None or v == "":
            return None
        if not isinstance(v, str):
            return None
        cleaned = v.strip()
        # Common symbol translations
        if cleaned in ("$", "US$"):
            return "USD"
        if cleaned == "€":
            return "EUR"
        if cleaned == "£":
            return "GBP"
        if cleaned in ("₹", "RS.", "RS", "INR", "Rs.", "Rs"):
            return "INR"
        # Validate 3-letter code
        upper = cleaned.upper()
        if re.match(r"^[A-Z]{3}$", upper):
            return upper
        return None

    @field_validator("subtotal", "tax", "discount", "tip", "final_total", mode="before")
    @classmethod
    def parse_optional_decimals(cls, v: Any) -> Decimal | None:
        if v is None or v == "":
            return None
        return _quantize_decimal(v)

    def evaluate_status(self) -> None:
        """Evaluates whether status is 'completed', 'review_required', or 'failed'."""
        if not self.is_receipt:
            self.status = "failed"
            self.document_type = "non_receipt"
            if not self.error_code:
                self.error_code = "NON_RECEIPT_DOCUMENT"
            if not self.error_message:
                self.error_message = self.rejection_reason or "Document does not qualify as a valid financial receipt or invoice."
            self.confidence = 0.0
            self.items = []
            self.merchant_name = None
            self.merchant_address = None
            self.receipt_date = None
            self.receipt_number = None
            self.currency = None
            self.subtotal = None
            self.tax = None
            self.tip = None
            self.discount = None
            self.final_total = None
            self.missing_fields = []
            self.uncertain_fields = []
            return

        if self.status == "failed":
            self.confidence = 0.0
            return

        if not self.document_type:
            self.document_type = "receipt"

        # Determine missing fields genuinely absent (never invent missing information)
        missing: list[str] = []
        if not self.merchant_name:
            missing.append("merchant_name")
        if not self.currency:
            missing.append("currency")
        if self.final_total is None:
            missing.append("final_total")
        if self.subtotal is None:
            missing.append("subtotal")
        if not self.items:
            missing.append("items")
        else:
            for it in self.items:
                if it.total_price is None and it.unit_price is None:
                    if "item_prices" not in missing:
                        missing.append("item_prices")
                if it.quantity is None:
                    if "item_quantities" not in missing:
                        missing.append("item_quantities")

        # Merge with existing missing_fields preserving uniqueness
        self.missing_fields = list(dict.fromkeys(self.missing_fields + missing))

        # Classify status
        if (
            self.missing_fields
            or self.uncertain_fields
            or self.confidence < 0.70
            or self.is_fallback
        ):
            self.status = "review_required"
        else:
            self.status = "completed"

    def validate_math_consistency(self) -> None:
        """Verifies mathematical consistency without calculating invented totals.
        
        Checks if subtotal + tax + tip - discount reconciles with final_total.
        Marks uncertain_fields and adjusts confidence if a discrepancy is found.
        """
        if self.final_total is not None and self.subtotal is not None:
            expected_total = (
                self.subtotal
                + (self.tax or Decimal("0.00"))
                + (self.tip or Decimal("0.00"))
                - (self.discount or Decimal("0.00"))
            ).quantize(Decimal("0.01"))

            diff = abs(self.final_total - expected_total)
            if diff > Decimal("0.05"):
                self.warnings.append(
                    f"Mathematical discrepancy: Subtotal ({self.subtotal}) + Tax ({self.tax or 0}) "
                    f"+ Tip ({self.tip or 0}) - Discount ({self.discount or 0}) = {expected_total}, "
                    f"differing from Total ({self.final_total}) by {diff}."
                )
                if "final_total" not in self.uncertain_fields:
                    self.uncertain_fields.append("final_total")
                if "subtotal" not in self.uncertain_fields:
                    self.uncertain_fields.append("subtotal")
                self.confidence = max(0.1, round(self.confidence * 0.85, 2))

        self.evaluate_status()

    # -------------------------------------------------------------------------
    # CONTRACT ADAPTERS
    # -------------------------------------------------------------------------

    def to_api_response(self) -> dict[str, Any]:
        """Returns the canonical approved API contract for SplitMate.
        
        Monetary values are serialized as decimal strings (e.g. '45.50') or null.
        All arrays (items, missing_fields, uncertain_fields, warnings) are always present.
        """
        items_payload = []
        for idx, item in enumerate(self.items):
            items_payload.append({
                "id": f"item_{idx + 1}",
                "item_name": item.item_name,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price) if item.unit_price is not None else None,
                "total_price": str(item.total_price) if item.total_price is not None else None,
            })

        return {
            "status": self.status,
            "document_type": self.document_type,
            "merchant_name": self.merchant_name,
            "currency": self.currency,
            "subtotal": str(self.subtotal) if self.subtotal is not None else None,
            "tax": str(self.tax) if self.tax is not None else None,
            "final_total": str(self.final_total) if self.final_total is not None else None,
            "total": str(self.final_total) if self.final_total is not None else None,
            "items": items_payload,
            "missing_fields": self.missing_fields,
            "uncertain_fields": self.uncertain_fields,
            "confidence": self.confidence,
            "warnings": self.warnings,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "is_receipt": self.is_receipt,
            "rejection_reason": self.rejection_reason,
            "merchant_address": self.merchant_address,
            "receipt_date": self.receipt_date,
            "receipt_number": self.receipt_number,
            "tip": str(self.tip) if self.tip is not None else None,
            "discount": str(self.discount) if self.discount is not None else None,
            "is_fallback": self.is_fallback,
            "extraction_method": self.extraction_method,
        }

    def to_backend_contract(self) -> dict[str, Any]:
        """Converts canonical extraction result into Tanishq's ReceiptExtractionRequest payload.
        
        Schema matches app.schemas.schemas.ReceiptExtractionRequest:
        - merchant_name: str
        - currency: str
        - subtotal: Decimal
        - tax: Decimal
        - total: Decimal
        - items: list[ReceiptItemExtraction]

        Strictly rejects non-receipt documents or extractions without items.
        Never generates dummy fallback items. Never fabricates 'Unknown Merchant'.
        """
        if not self.is_receipt:
            raise ValueError(
                f"Cannot generate backend contract for non-receipt document: "
                f"{self.rejection_reason or self.error_message or 'Document was rejected as a non-receipt.'}"
            )

        if not self.items:
            raise ValueError(
                "Cannot generate backend contract: No line items extracted from receipt. "
                "Receipts must contain at least 1 verified line item."
            )

        if not self.merchant_name:
            raise ValueError(
                "Cannot generate backend contract: merchant_name is missing. "
                "Review is required before persisting to backend."
            )

        merchant = self.merchant_name.strip()
        subtotal_val = self.subtotal if self.subtotal is not None else Decimal("0.00")
        tax_val = self.tax if self.tax is not None else Decimal("0.00")
        total_val = self.final_total if self.final_total is not None else (subtotal_val + tax_val)

        items_payload = []
        for item in self.items:
            tot = item.total_price if item.total_price is not None else Decimal("0.00")
            unit = item.unit_price if item.unit_price is not None else tot
            qty = item.quantity if item.quantity is not None else 1
            items_payload.append({
                "item_name": item.item_name,
                "quantity": qty,
                "unit_price": str(unit),
                "total_price": str(tot),
            })

        return {
            "merchant_name": merchant,
            "currency": self.currency,
            "subtotal": str(subtotal_val),
            "tax": str(tax_val),
            "total": str(total_val),
            "items": items_payload,
        }

    def to_frontend_contract(self) -> dict[str, Any]:
        """Converts canonical extraction result into Dhruv's React frontend format.
        
        Matches structure expected by ExtractionResult.jsx, ReceiptPreview.jsx, and ExpenseContext.jsx:
        - status: str ('completed', 'review_required', 'failed')
        - success: bool (False if non-receipt or rejected)
        - is_receipt: bool
        - rejection_reason: str | None
        - error_code: str | None
        - error_message: str | None
        - merchant: str | None (never fabricated)
        - date: str
        - category: str
        - currency: str | None
        - subtotal: float
        - tax: float
        - tip: float
        - discount: float
        - total: float
        - confidence: float
        - missing_fields: list[str]
        - uncertain_fields: list[str]
        - warnings: list[str]
        - items: list with id, name, item_name, quantity, price, unit_price, total_price
        """
        items_payload = []
        is_valid = self.is_receipt and self.status != "failed" and bool(self.items or self.final_total is not None)

        if is_valid:
            for idx, item in enumerate(self.items):
                tot = float(item.total_price) if item.total_price is not None else 0.0
                unit = float(item.unit_price) if item.unit_price is not None else tot
                items_payload.append({
                    "id": f"item_{idx + 1}",
                    "name": item.item_name,
                    "item_name": item.item_name,
                    "quantity": item.quantity or 1,
                    "price": tot,
                    "unit_price": float(unit),
                    "total_price": float(tot),
                    "unit_price_str": str(item.unit_price) if item.unit_price is not None else None,
                    "total_price_str": str(item.total_price) if item.total_price is not None else None,
                })

        return {
            "status": self.status,
            "document_type": self.document_type,
            "success": is_valid,
            "is_receipt": self.is_receipt,
            "rejection_reason": self.rejection_reason,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "merchant": self.merchant_name if is_valid else None,
            "merchant_name": self.merchant_name if is_valid else None,
            "merchant_address": self.merchant_address if is_valid else None,
            "date": (self.receipt_date or "") if is_valid else "",
            "receipt_number": self.receipt_number if is_valid else None,
            "category": "Food & Dining" if is_valid else "Non-Receipt",
            "currency": self.currency,
            "subtotal": float(self.subtotal) if (is_valid and self.subtotal is not None) else 0.0,
            "tax": float(self.tax) if (is_valid and self.tax is not None) else 0.0,
            "tip": float(self.tip) if (is_valid and self.tip is not None) else 0.0,
            "discount": float(self.discount) if (is_valid and self.discount is not None) else 0.0,
            "total": float(self.final_total) if (is_valid and self.final_total is not None) else 0.0,
            "final_total": float(self.final_total) if (is_valid and self.final_total is not None) else 0.0,
            "subtotal_str": str(self.subtotal) if (is_valid and self.subtotal is not None) else None,
            "tax_str": str(self.tax) if (is_valid and self.tax is not None) else None,
            "total_str": str(self.final_total) if (is_valid and self.final_total is not None) else None,
            "final_total_str": str(self.final_total) if (is_valid and self.final_total is not None) else None,
            "confidence": self.confidence,
            "missing_fields": self.missing_fields,
            "uncertain_fields": self.uncertain_fields,
            "is_fallback": self.is_fallback,
            "extraction_method": self.extraction_method,
            "warnings": self.warnings,
            "items": items_payload,
        }

