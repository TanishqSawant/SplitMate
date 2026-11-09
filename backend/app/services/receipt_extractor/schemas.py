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
    """Line item extracted from receipt."""
    item_name: str = Field(..., min_length=1, max_length=255, description="Name or description of line item")
    quantity: int = Field(default=1, ge=1, description="Quantity purchased, at least 1")
    unit_price: Decimal = Field(default=Decimal("0.00"), ge=0, description="Unit price per item")
    total_price: Decimal = Field(default=Decimal("0.00"), ge=0, description="Total price for line item (quantity * unit_price)")

    @field_validator("unit_price", "total_price", mode="before")
    @classmethod
    def round_prices(cls, v: Any) -> Decimal:
        quantized = _quantize_decimal(v)
        return quantized if quantized is not None else Decimal("0.00")

    @model_validator(mode="after")
    def reconcile_item_total(self) -> "ExtractedLineItem":
        # If total_price is 0 but unit_price and quantity exist, compute total_price
        if self.total_price == Decimal("0.00") and self.unit_price > Decimal("0.00"):
            self.total_price = (self.unit_price * self.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif self.unit_price == Decimal("0.00") and self.total_price > Decimal("0.00") and self.quantity > 0:
            self.unit_price = (self.total_price / self.quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return self


class ReceiptExtractionResult(BaseModel):
    """Canonical structured receipt extraction output containing all 12 required fields.
    
    Adheres strictly to the rule: Never hallucinate missing receipt information. Use null where unavailable.
    """
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
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Overall confidence score (0.0 to 1.0)")
    is_fallback: bool = Field(default=False, description="True if heuristic/regex fallback was used instead of primary AI model")
    extraction_method: str = Field(default="gemini_vision", description="Method name: gemini_vision or regex_heuristic_fallback")
    warnings: list[str] = Field(default_factory=list, description="Quality warnings, blur notices, or missing field diagnostics")

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

    def validate_math_consistency(self) -> None:
        """Verifies if subtotal + tax + tip - discount reconciles with final_total.
        
        Adjusts confidence score and adds warnings if there is a discrepancy, but never fabricates numbers.
        """
        # If line items exist but subtotal is null, compute derived subtotal
        item_sum = sum(item.total_price for item in self.items)
        if self.subtotal is None and self.items:
            self.subtotal = item_sum.quantize(Decimal("0.01"))
            self.warnings.append("Subtotal was derived from line items sum.")

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
                self.confidence = max(0.1, round(self.confidence * 0.85, 2))

    # -------------------------------------------------------------------------
    # CONTRACT ADAPTERS
    # -------------------------------------------------------------------------

    def to_backend_contract(self) -> dict[str, Any]:
        """Converts canonical extraction result into Tanishq's ReceiptExtractionRequest payload.
        
        Schema matches app.schemas.schemas.ReceiptExtractionRequest:
        - merchant_name: str
        - currency: str
        - subtotal: Decimal
        - tax: Decimal
        - total: Decimal
        - items: list[ReceiptItemExtraction]
        """
        merchant = self.merchant_name.strip() if self.merchant_name else "Unknown Merchant"
        subtotal_val = self.subtotal if self.subtotal is not None else Decimal("0.00")
        tax_val = self.tax if self.tax is not None else Decimal("0.00")
        total_val = self.final_total if self.final_total is not None else (subtotal_val + tax_val)

        items_payload = []
        if self.items:
            for item in self.items:
                items_payload.append({
                    "item_name": item.item_name,
                    "quantity": item.quantity,
                    "unit_price": str(item.unit_price),
                    "total_price": str(item.total_price),
                })
        else:
            # Backend contract requires items list with at least 1 item
            items_payload.append({
                "item_name": "Receipt Total",
                "quantity": 1,
                "unit_price": str(total_val),
                "total_price": str(total_val),
            })

        if not self.currency:
            if "Currency was not detected on receipt; defaulted to USD for backend schema compliance." not in self.warnings:
                self.warnings.append("Currency was not detected on receipt; defaulted to USD for backend schema compliance.")

        return {
            "merchant_name": merchant,
            "currency": self.currency or "USD",
            "subtotal": str(subtotal_val),
            "tax": str(tax_val),
            "total": str(total_val),
            "items": items_payload,
        }

    def to_frontend_contract(self) -> dict[str, Any]:
        """Converts canonical extraction result into Dhruv's React frontend format.
        
        Matches structure expected by ExtractionResult.jsx, ReceiptPreview.jsx, and ExpenseContext.jsx:
        - merchant: str (with merchant_name alias)
        - date: str
        - category: str
        - currency: str
        - subtotal: float
        - tax: float
        - tip: float
        - discount: float
        - total: float
        - confidence: float
        - is_fallback: bool
        - warnings: list[str]
        - items: list with id, name, item_name, quantity, price, unit_price, total_price
        """
        items_payload = []
        for idx, item in enumerate(self.items):
            items_payload.append({
                "id": f"item_{idx + 1}",
                "name": item.item_name,
                "item_name": item.item_name,
                "quantity": item.quantity,
                "price": float(item.total_price),
                "unit_price": float(item.unit_price),
                "total_price": float(item.total_price),
            })

        return {
            "merchant": self.merchant_name or "Unknown Merchant",
            "merchant_name": self.merchant_name or "Unknown Merchant",
            "merchant_address": self.merchant_address,
            "date": self.receipt_date or "",
            "receipt_number": self.receipt_number,
            "category": "Food & Dining",
            "currency": self.currency or "USD",
            "subtotal": float(self.subtotal) if self.subtotal is not None else 0.0,
            "tax": float(self.tax) if self.tax is not None else 0.0,
            "tip": float(self.tip) if self.tip is not None else 0.0,
            "discount": float(self.discount) if self.discount is not None else 0.0,
            "total": float(self.final_total) if self.final_total is not None else 0.0,
            "confidence": self.confidence,
            "is_fallback": self.is_fallback,
            "extraction_method": self.extraction_method,
            "warnings": self.warnings,
            "items": items_payload,
        }

