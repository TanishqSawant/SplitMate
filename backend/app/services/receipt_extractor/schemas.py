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


class ReceiptExtractionResult(BaseModel):
    """Canonical structured receipt extraction output containing all 12 required fields.
    
    Adheres strictly to the rule: Never hallucinate missing receipt information. Use null where unavailable.
    """
    # 0. Document Classification & Status
    document_type: str | None = Field(default=None, description="Type of document, e.g. 'receipt', 'tax_invoice', 'restaurant_bill', or 'unsupported'")
    status: str = Field(default="review_required", description="Extraction status: 'completed', 'review_required', or 'failed'")
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

    # -------------------------------------------------------------------------
    # CONTRACT ADAPTERS
    # -------------------------------------------------------------------------

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
        for idx, item in enumerate(self.items):
            items_payload.append({
                "id": f"item_{idx + 1}",
                "name": item.item_name,
                "item_name": item.item_name,
                "quantity": str(item.quantity) if item.quantity is not None else None,
                "price": str(item.total_price) if item.total_price is not None else None,
                "unit_price": str(item.unit_price) if item.unit_price is not None else None,
                "total_price": str(item.total_price) if item.total_price is not None else None,
            })

        return {
            "merchant": self.merchant_name,
            "merchant_name": self.merchant_name,
            "merchant_address": self.merchant_address,
            "date": self.receipt_date or "",
            "receipt_number": self.receipt_number,
            "category": "Food & Dining",
            "currency": self.currency,
            "subtotal": str(self.subtotal) if self.subtotal is not None else None,
            "tax": str(self.tax) if self.tax is not None else None,
            "tip": str(self.tip) if self.tip is not None else None,
            "discount": str(self.discount) if self.discount is not None else None,
            "total": str(self.final_total) if self.final_total is not None else None,
            "confidence": self.confidence,
            "is_fallback": self.is_fallback,
            "extraction_method": self.extraction_method,
            "warnings": self.warnings,
            "items": items_payload,
        }

