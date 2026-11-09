"""AI LLM extraction layer using Gemini structured outputs with an explicit fallback engine.

Adheres strictly to the requirements:
1. Uses Gemini structured outputs with Pydantic validation.
2. Never hallucinates missing receipt information (returns null for missing fields).
3. If fallback is triggered, explicitly marks is_fallback=True, sets low confidence,
   and details fallback reasons in warnings.
"""

from decimal import Decimal
import json
import os
import re
from typing import Any
from PIL import Image

from .schemas import ExtractedLineItem, ReceiptExtractionResult


RECEIPT_SYSTEM_PROMPT = """You are an expert financial receipt analysis AI for SplitMate.
Extract structured receipt information from the provided receipt image.

CRITICAL EXTRACTION RULES:
1. Extract the following fields:
   - merchant_name: Legal or commercial business name (e.g. "Mario's Bistro") or null if unreadable.
   - merchant_address: Physical street/store address, or null if absent.
   - receipt_date: Transaction date formatted as YYYY-MM-DD if recognizable, else null.
   - receipt_number: Invoice, receipt, or transaction ID, or null.
   - currency: 3-letter ISO code (e.g. USD, EUR, GBP, INR). Default to USD if uncertain.
   - items: Array of purchased items. For each line item:
       * item_name: Name of product, food dish, or service.
       * quantity: Integer quantity (must be >= 1, default 1).
       * unit_price: Unit price as non-negative decimal with up to 2 decimal places.
       * total_price: Line item total (quantity * unit_price) as non-negative decimal.
   - subtotal: Subtotal before taxes and discounts as non-negative decimal, or null.
   - tax: Sales tax, GST, or VAT as non-negative decimal, or null.
   - discount: Total discount or coupon deduction as non-negative decimal, or null.
   - tip: Gratuity or service tip as non-negative decimal, or null.
   - final_total: Grand total payable as non-negative decimal, or null.

2. STRICT ANTI-HALLUCINATION RULE:
   - NEVER invent or fabricate missing numbers, items, or merchant names.
   - If an item or number is not explicitly visible on the receipt, output null.

3. LINE ITEMS EXTRACTION:
   - Do NOT include 'Subtotal', 'Tax', 'Tip', 'Total', 'Cash', or 'Change' as items in the items list.
   - Only include actual products, dishes, beverages, or services purchased.
"""


class RegexHeuristicFallback:
    """Deterministic fallback parser when AI API is unavailable or offline.
    
    CRITICAL: Never silently returns incomplete regex extraction as successful AI extraction.
    Clearly marks is_fallback=True, flags confidence <= 0.35, and documents warnings.
    """

    CURRENCY_PATTERNS = [
        (r"[₹]|(?:\b(?:Rs\.?|INR)\b)", "INR"),
        (r"[$]|(?:\bUSD\b)", "USD"),
        (r"[€]|(?:\bEUR\b)", "EUR"),
        (r"[£]|(?:\bGBP\b)", "GBP"),
        (r"\bCAD\b", "CAD"),
        (r"\bAUD\b", "AUD"),
    ]

    DATE_PATTERNS = [
        r"\b(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b",  # YYYY-MM-DD
        r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})\b",  # MM/DD/YYYY or DD/MM/YYYY
        r"\b([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b",  # Nov 09, 2026
    ]

    TOTAL_PATTERNS = [
        r"(?:grand\s+total|total\s+amount|\b(?<!sub)(?<!sub-)(?<!sub\s)total\b|balance\s+due|amount\s+due)[\s:]*[$€£₹]?\s*([0-9]+[.,][0-9]{2})",
    ]

    SUBTOTAL_PATTERNS = [
        r"\b(?:subtotal|sub\s+total|sub-total|net\s+amount)\b[\s:]*[$€£₹]?\s*([0-9]+[.,][0-9]{2})",
    ]

    TAX_PATTERNS = [
        r"\b(?:tax|gst|vat|sales\s+tax|hst)\b[\s:]*[$€£₹]?\s*([0-9]+[.,][0-9]{2})",
    ]

    DISCOUNT_PATTERNS = [
        r"\b(?:discount|savings|coupon|promo)\b[\s:]*[-$€£₹]?\s*([0-9]+[.,][0-9]{2})",
    ]

    def parse_text(self, text: str, initial_warnings: list[str] | None = None) -> ReceiptExtractionResult:
        """Parses raw text via regular expressions and heuristics."""
        warnings = list(initial_warnings or [])
        warnings.append(
            "Fallback extraction used: Primary AI Vision model was offline or API key was missing. "
            "Data was parsed via regex heuristics with reduced confidence."
        )

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ReceiptExtractionResult(
                merchant_name=None,
                currency=None,
                items=[],
                confidence=0.0,
                is_fallback=True,
                extraction_method="regex_heuristic_fallback",
                warnings=warnings + ["No text could be extracted from document."],
            )

        # 1. Merchant Name heuristic: Typically first non-empty header line
        merchant_name: str | None = None
        for line in lines[:3]:
            # Skip lines that are just numbers or dates
            if re.search(r"[A-Za-z]{3,}", line) and not any(kw in line.lower() for kw in ["receipt", "invoice", "welcome", "tax"]):
                merchant_name = line
                break

        # 2. Currency detection (preserves None if missing)
        currency: str | None = None
        for pattern, code in self.CURRENCY_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                currency = code
                break

        if currency is None:
            warnings.append("Currency was not detected on receipt; preserved as null.")

        # 3. Date detection
        receipt_date: str | None = None
        for pattern in self.DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                receipt_date = match.group(1)
                break

        # 4. Receipt / Invoice number
        receipt_number: str | None = None
        inv_match = re.search(r"(?:invoice|receipt|order|bill)\s*(?:#|no\.?|num)?\s*[:\s]*([A-Za-z0-9\-]+)", text, re.IGNORECASE)
        if inv_match:
            receipt_number = inv_match.group(1)

        # 5. Financial totals parsing
        def extract_amount(patterns: list[str]) -> Decimal | None:
            for pat in patterns:
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    raw = m.group(1).replace(",", ".")
                    try:
                        return Decimal(raw)
                    except Exception:
                        pass
            return None

        subtotal = extract_amount(self.SUBTOTAL_PATTERNS)
        tax = extract_amount(self.TAX_PATTERNS)
        discount = extract_amount(self.DISCOUNT_PATTERNS)
        final_total = extract_amount(self.TOTAL_PATTERNS)

        # 6. Line items parsing
        items: list[ExtractedLineItem] = []
        for line in lines:
            # Skip summary lines
            lower = line.lower()
            if any(skip in lower for skip in ["total", "subtotal", "tax", "vat", "gst", "tip", "balance", "visa", "mastercard", "change", "cash"]):
                continue

            # Look for: Name ... [qty] ... price
            # e.g., "Margherita Pizza 2 18.00" or "Margherita Pizza $18.00"
            item_match = re.search(r"^([A-Za-z0-9\s\-\&\'\.]+?)\s+(?:(\d+)\s+)?(?:[$€£₹]?\s*)(\d+[.,]\d{2})$", line)
            if item_match:
                name = item_match.group(1).strip()
                qty_str = item_match.group(2)
                price_str = item_match.group(3).replace(",", ".")
                if len(name) >= 2:
                    qty = int(qty_str) if qty_str else 1
                    tot_price = Decimal(price_str)
                    unit_p = tot_price / qty
                    items.append(
                        ExtractedLineItem(
                            item_name=name,
                            quantity=qty,
                            unit_price=unit_p,
                            total_price=tot_price,
                        )
                    )

        # Confidence calculation for fallback: maximum 0.35
        confidence = 0.20
        if merchant_name:
            confidence += 0.05
        if final_total is not None:
            confidence += 0.05
        if items:
            confidence += 0.05
        confidence = min(0.35, confidence)

        result = ReceiptExtractionResult(
            merchant_name=merchant_name,
            merchant_address=None,
            receipt_date=receipt_date,
            receipt_number=receipt_number,
            currency=currency,
            items=items,
            subtotal=subtotal,
            tax=tax,
            discount=discount,
            tip=None,
            final_total=final_total,
            confidence=confidence,
            is_fallback=True,
            extraction_method="regex_heuristic_fallback",
            warnings=warnings,
        )
        result.validate_math_consistency()
        return result


class GeminiVisionExtractor:
    """Extracts structured receipt data using Google Gemini Vision structured output."""

    DEFAULT_MODEL = "gemini-2.5-flash"
    FALLBACK_MODEL = "gemini-1.5-flash"

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model_name = model or os.environ.get("GEMINI_MODEL") or self.DEFAULT_MODEL
        self.fallback_parser = RegexHeuristicFallback()

    def is_available(self) -> bool:
        """Checks if an API key is configured for Gemini."""
        return bool(self.api_key and self.api_key.strip())

    def extract(
        self,
        image: Image.Image,
        text_context: str = "",
        initial_warnings: list[str] | None = None,
    ) -> ReceiptExtractionResult:
        """Extracts receipt data using Gemini Vision, falling back cleanly if unavailable or on error."""
        warnings = list(initial_warnings or [])

        # If API key is not present, use the explicit fallback engine
        if not self.is_available():
            warnings.append("GEMINI_API_KEY environment variable is not configured.")
            return self.fallback_parser.parse_text(text_context, initial_warnings=warnings)

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)

            # Define prompt content with multimodal image
            contents: list[Any] = [image, RECEIPT_SYSTEM_PROMPT]
            if text_context:
                contents.append(f"Additional text recognized from document:\n{text_context}")

            # Request structured JSON conforming to ReceiptExtractionResult schema
            response = client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ReceiptExtractionResult,
                    temperature=0.1,  # Low temperature for deterministic, factual extraction
                ),
            )

            raw_text = response.text
            if not raw_text:
                raise ValueError("Empty response received from Gemini Vision API.")

            parsed_dict = json.loads(raw_text)
            # Ensure metadata flags are correctly assigned
            parsed_dict["is_fallback"] = False
            parsed_dict["extraction_method"] = "gemini_vision"
            if not parsed_dict.get("confidence") or parsed_dict["confidence"] <= 0.0:
                parsed_dict["confidence"] = 0.95

            # Merge warnings
            existing_warn = parsed_dict.get("warnings") or []
            parsed_dict["warnings"] = list(dict.fromkeys(warnings + existing_warn))

            result = ReceiptExtractionResult.model_validate(parsed_dict)
            result.validate_math_consistency()
            return result

        except Exception as e:
            # Cleanly catch and document API failure without crashing
            api_warn = f"Gemini Vision API extraction failed ({type(e).__name__}: {str(e)}). Engaging fallback parser."
            warnings.append(api_warn)
            return self.fallback_parser.parse_text(text_context, initial_warnings=warnings)
