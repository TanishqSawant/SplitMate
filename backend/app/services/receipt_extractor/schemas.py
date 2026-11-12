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
    """Helper to cleanly round and quantize monetary values to 2 decimal places.

    Preserves None and raises ValueError for invalid/malformed numeric values.
    """
    if value is None or value == "":
        return None
    try:
        dec = Decimal(str(value))
    except Exception as e:
        raise ValueError(f"Invalid numeric value: {value}") from e
    return dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _parse_quantity(value: Decimal | float | int | str | None) -> Decimal | None:
    """Parse quantity as Decimal, preserving fractional quantities, explicit zero, and None.

    Raises ValueError for invalid/malformed numeric values.
    """
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception as e:
        raise ValueError(f"Invalid numeric value for quantity: {value}") from e


class ExtractedLineItem(BaseModel):
    """Line item extracted from receipt."""
    item_name: str = Field(..., min_length=1, max_length=255, description="Name or description of line item")
    quantity: Decimal | None = Field(default=None, ge=0, description="Quantity purchased, may be fractional (e.g. 0.5)")
    unit_price: Decimal | None = Field(default=None, ge=0, description="Unit price per item")
    total_price: Decimal | None = Field(default=None, ge=0, description="Total price for line item (quantity * unit_price)")

    @field_validator("quantity", mode="before")
    @classmethod
    def parse_quantity_validator(cls, v: Any) -> Decimal | None:
        return _parse_quantity(v)

    @field_validator("unit_price", "total_price", mode="before")
    @classmethod
    def round_prices(cls, v: Any) -> Decimal | None:
        return _quantize_decimal(v)

    def to_dict(self) -> dict[str, Any]:
        """Serializes line item preserving Decimal values and nulls."""
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
    # 0. Document Classification & Status
    status: str = Field(default="review_required", description="Extraction status: 'completed', 'review_required', or 'failed'")
    document_type: str | None = Field(default=None, description="Type of document, e.g. 'receipt', 'tax_invoice', 'restaurant_bill', or 'unsupported'")
    is_receipt: bool = Field(default=True, description="True if document is a valid financial receipt/invoice, False if non-receipt, academic, or rejected")
    rejection_reason: str | None = Field(default=None, description="Detailed explanation if document was rejected as non-receipt")
    error_code: str | None = Field(default=None, description="Sanitized machine-readable error code if status == 'failed'")
    error_message: str | None = Field(default=None, description="Sanitized human-readable error description")

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

    # 5. Financial Totals
    subtotal: Decimal | None = Field(default=None, ge=0, description="Subtotal before taxes and discounts, or null")
    tax: Decimal | None = Field(default=None, ge=0, description="GST / VAT / Sales tax amount, or null")
    discount: Decimal | None = Field(default=None, ge=0, description="Discounts or coupons applied, or null")
    tip: Decimal | None = Field(default=None, ge=0, description="Gratuity or tip, or null")
    final_total: Decimal | None = Field(default=None, ge=0, description="Final payable amount, or null")

    # 6. Extraction Quality Metadata
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="Overall confidence score (0.0 to 1.0) or null")
    is_fallback: bool = Field(default=False, description="True if heuristic/regex fallback was used instead of primary AI model")
    extraction_method: str = Field(default="gemini_vision", description="Method name: gemini_vision or regex_heuristic_fallback")
    warnings: list[str] = Field(default_factory=list, description="Quality warnings, blur notices, or missing field diagnostics")
    missing_fields: list[str] = Field(default_factory=list, description="List of expected receipt fields not detected")
    uncertain_fields: list[str] = Field(default_factory=list, description="List of fields extracted with low confidence or ambiguity")

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, v: Any) -> str:
        if v is None or v == "":
            return "review_required"
        if isinstance(v, str):
            cleaned = v.strip().lower()
            if cleaned in ("completed", "review_required", "failed"):
                return cleaned
        return "review_required"

    @model_validator(mode="after")
    def clean_non_receipt_fields(self) -> "ReceiptExtractionResult":
        """Ensures that non-receipt documents never leak extracted fields."""
        if not self.is_receipt or self.document_type == "non_receipt":
            self.status = "failed"
            self.document_type = "non_receipt"
            if not self.error_code:
                self.error_code = "NON_RECEIPT_DOCUMENT"
            if not self.error_message:
                self.error_message = self.rejection_reason or "Document does not qualify as a valid financial receipt or invoice."
            if self.confidence != 0.0:
                self.confidence = None
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
        return self

    @model_validator(mode="before")
    @classmethod
    def check_ambiguous_currency(cls, data: Any) -> Any:
        """Detects ambiguous currency symbols like standalone '$' and marks currency as uncertain."""
        if isinstance(data, dict):
            raw_curr = data.get("currency")
            if isinstance(raw_curr, str) and raw_curr.strip() == "$":
                uncertain = list(data.get("uncertain_fields") or [])
                if "currency" not in uncertain:
                    uncertain.append("currency")
                data["uncertain_fields"] = uncertain
                warnings = list(data.get("warnings") or [])
                warn_msg = "Ambiguous currency symbol '$' detected without country code."
                if warn_msg not in warnings:
                    warnings.append(warn_msg)
                data["warnings"] = warnings
        return data

    @field_validator("currency", mode="before")
    @classmethod
    def clean_currency(cls, v: Any) -> str | None:
        if v is None or v == "":
            return None
        if not isinstance(v, str):
            return None
        cleaned = v.strip()
        # Common symbol translations
        if cleaned == "US$":
            return "USD"
        if cleaned == "$":
            return None
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

    def validate_math_consistency(self) -> None:
        """Validates arithmetic consistency across line items and financial totals without inventing data.

        1. Validates quantity × unit_price against total_price for line items when all three values are available,
           flagging any mismatch after cent quantization (one-cent discrepancies do not pass).
        2. Preserves missing values (does NOT treat missing subtotal, tax, tip, or discount as zero).
        3. Only performs financial reconciliation when subtotal, tax, tip, discount, and final_total are all present.
        4. Preserves genuine model confidence without arbitrary adjustment.
        """
        # Validate individual line items when all three are present
        for item in self.items:
            if item.quantity is not None and item.unit_price is not None and item.total_price is not None:
                expected_item_total = (item.quantity * item.unit_price).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                quantized_total_price = item.total_price.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if quantized_total_price != expected_item_total:
                    self.warnings.append(
                        f"Line item math discrepancy for '{item.item_name}': "
                        f"{item.quantity} × {item.unit_price} = {expected_item_total}, "
                        f"differing from total_price {item.total_price}."
                    )

        # Reconcile subtotal + tax + tip - discount vs final_total ONLY when
        # subtotal, tax, tip, discount, and final_total are ALL present (non-None).
        # If any of these values is None, skip total reconciliation without generating a warning.
        if (
            self.final_total is not None
            and self.subtotal is not None
            and self.tax is not None
            and self.tip is not None
            and self.discount is not None
        ):
            expected_total = (self.subtotal + self.tax + self.tip - self.discount).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            quantized_final_total = self.final_total.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if quantized_final_total != expected_total:
                diff = abs(quantized_final_total - expected_total)
                self.warnings.append(
                    f"Mathematical discrepancy: Subtotal ({self.subtotal}) + Tax ({self.tax}) "
                    f"+ Tip ({self.tip}) - Discount ({self.discount}) = {expected_total}, "
                    f"differing from Total ({self.final_total}) by {diff}."
                )

    def evaluate_status(self) -> None:
        """Evaluates whether status is 'completed', 'review_required', or 'failed'."""
        if not self.is_receipt:
            self.status = "failed"
            self.document_type = "non_receipt"
            if not self.error_code:
                self.error_code = "NON_RECEIPT_DOCUMENT"
            if not self.error_message:
                self.error_message = self.rejection_reason or "Document does not qualify as a valid financial receipt or invoice."
            if self.confidence != 0.0:
                self.confidence = None
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
            or self.confidence is None
            or self.confidence < 0.70
            or self.is_fallback
        ):
            self.status = "review_required"
        else:
            self.status = "completed"

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
            "document_type": self.document_type,
            "merchant_name": self.merchant_name,
            "currency": self.currency,
            "subtotal": str(self.subtotal) if self.subtotal is not None else None,
            "tax": str(self.tax) if self.tax is not None else None,
            "final_total": str(self.final_total) if self.final_total is not None else None,
            "total": str(self.final_total) if self.final_total is not None else None,
            "items": items_payload,
            "missing_fields": list(self.missing_fields),
            "uncertain_fields": list(self.uncertain_fields),
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "status": self.status,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "is_receipt": self.is_receipt,
            "rejection_reason": self.rejection_reason,
            "merchant_address": self.merchant_address,
            "receipt_date": self.receipt_date,
            "receipt_number": self.receipt_number,
        }

    def to_backend_contract(self) -> dict[str, Any]:
        """Converts canonical extraction result into Tanishq's ReceiptExtractionRequest payload.
        
        Preserves None for missing fields; never invents merchant, currency, subtotal, tax,
        total, or fallback items.
        """
        merchant = self.merchant_name.strip() if self.merchant_name else None
        subtotal_val = str(self.subtotal) if self.subtotal is not None else None
        tax_val = str(self.tax) if self.tax is not None else None
        total_val = str(self.final_total) if self.final_total is not None else None

        items_payload = []
        for item in self.items:
            items_payload.append({
                "item_name": item.item_name,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price) if item.unit_price is not None else None,
                "total_price": str(item.total_price) if item.total_price is not None else None,
            })

        return {
            "merchant_name": merchant,
            "currency": self.currency,
            "subtotal": subtotal_val,
            "tax": tax_val,
            "total": total_val,
            "items": items_payload,
            "extraction_status": self.status,
            "status": self.status,
            "missing_fields": self.missing_fields,
            "uncertain_fields": self.uncertain_fields,
            "warnings": self.warnings,
            "confidence": self.confidence,
            "document_type": self.document_type,
        }

    def to_frontend_contract(self) -> dict[str, Any]:
        """Converts canonical extraction result into Dhruv's React frontend format.

        Preserves None for missing fields; never fabricates defaults.
        """
        items_payload = []
        is_valid = self.is_receipt and self.status != "failed" and bool(self.items or self.final_total is not None)

        if is_valid:
            for idx, item in enumerate(self.items):
                tot = str(item.total_price) if item.total_price is not None else None
                unit = str(item.unit_price) if item.unit_price is not None else None
                qty = str(item.quantity) if item.quantity is not None else None
                items_payload.append({
                    "id": f"item_{idx + 1}",
                    "name": item.item_name,
                    "item_name": item.item_name,
                    "quantity": qty,
                    "price": tot,
                    "unit_price": unit,
                    "total_price": tot,
                    "unit_price_str": unit,
                    "total_price_str": tot,
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
            "currency": self.currency if is_valid else None,
            "subtotal": str(self.subtotal) if (is_valid and self.subtotal is not None) else None,
            "tax": str(self.tax) if (is_valid and self.tax is not None) else None,
            "tip": str(self.tip) if (is_valid and self.tip is not None) else None,
            "discount": str(self.discount) if (is_valid and self.discount is not None) else None,
            "total": str(self.final_total) if (is_valid and self.final_total is not None) else None,
            "final_total": str(self.final_total) if (is_valid and self.final_total is not None) else None,
            "subtotal_str": str(self.subtotal) if (is_valid and self.subtotal is not None) else None,
            "tax_str": str(self.tax) if (is_valid and self.tax is not None) else None,
            "total_str": str(self.final_total) if (is_valid and self.final_total is not None) else None,
            "final_total_str": str(self.final_total) if (is_valid and self.final_total is not None) else None,
            "confidence": self.confidence,
            "missing_fields": list(self.missing_fields),
            "uncertain_fields": list(self.uncertain_fields),
            "is_fallback": self.is_fallback,
            "extraction_method": self.extraction_method,
            "warnings": list(self.warnings),
            "items": items_payload,
        }

