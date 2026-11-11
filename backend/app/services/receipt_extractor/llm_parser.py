"""AI LLM extraction layer using Gemini structured outputs.

Adheres strictly to the requirements:
1. Uses Gemini structured outputs with Pydantic validation.
2. Never hallucinates missing receipt information (returns null for missing fields).
3. Production extraction uses Gemini only; heuristic fallback is disabled in production.
4. Error states produce controlled failed results with sanitized error codes and messages.
"""

from decimal import Decimal
import json
import logging
import re
from typing import Any
from PIL import Image

from app.core.config import settings
from .schemas import ExtractedLineItem, ReceiptExtractionResult

logger = logging.getLogger(__name__)


RECEIPT_SYSTEM_PROMPT = """You are an expert financial receipt analysis AI for SplitMate.
Extract structured receipt information from the provided receipt image.

CRITICAL EXTRACTION RULES:
1. Extract the following fields:
   - document_type: Document classification ("receipt", "tax_invoice", "restaurant_bill", "digital_invoice", or "unsupported" if not a receipt/bill).
   - status: "completed" if all essential fields and line items are clearly readable; "review_required" if partially readable or uncertain; "failed" if unreadable or not a receipt.
   - merchant_name: Legal or commercial business name (e.g. "Mario's Bistro") or null if unreadable.
   - merchant_address: Physical street/store address, or null if absent.
   - receipt_date: Transaction date formatted as YYYY-MM-DD if recognizable, else null.
   - receipt_number: Invoice, receipt, or transaction ID, or null.
   - currency: 3-letter ISO code (e.g. USD, EUR, GBP, INR) or null if not detected or ambiguous. NEVER default currency to USD. If only a bare '$' is present without country code (US$, CAD, AUD), set currency to null and add 'currency' to uncertain_fields.
   - items: Array of purchased items. For each line item:
       * item_name: Name of product, food dish, or service.
       * quantity: Quantity (integer or decimal >= 0.01).
       * unit_price: Unit price as non-negative decimal with up to 2 decimal places, or null if unreadable.
       * total_price: Line item total (quantity * unit_price) as non-negative decimal, or null if unreadable.
   - subtotal: Subtotal before taxes and discounts as non-negative decimal, or null.
   - tax: Sales tax, GST, or VAT as non-negative decimal, or null.
   - discount: Total discount or coupon deduction as non-negative decimal, or null.
   - tip: Gratuity or service tip as non-negative decimal, or null.
   - final_total: Grand total payable as non-negative decimal, or null.
   - missing_fields: List of expected receipt fields that could not be detected.
   - uncertain_fields: List of fields where text was partially blurred or confidence is low.

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
    Clearly marks is_fallback=True, preserves confidence=None, and documents warnings.
    """

    CURRENCY_PATTERNS = [
        (r"[₹]|(?:\b(?:Rs\.?|INR)\b)", "INR"),
        (r"(?:\bUSD\b|US\$)", "USD"),
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
                confidence=None,
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

        # 2. Currency detection (preserves None if missing or ambiguous)
        currency: str | None = None
        uncertain_fields: list[str] = []
        for pattern, code in self.CURRENCY_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                currency = code
                break

        if currency is None:
            if re.search(r"[$]", text):
                warnings.append("Ambiguous currency symbol '$' detected without country code.")
                uncertain_fields.append("currency")
            else:
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

        # Fallback extraction has no genuine model confidence score; preserve None
        confidence = None

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
            uncertain_fields=uncertain_fields,
        )
        result.validate_math_consistency()
        return result


class GeminiVisionExtractor:
    """Extracts structured receipt data using Google Gemini Vision structured output."""

    DEFAULT_MODEL = "gemini-2.5-flash"
    DEFAULT_TIMEOUT_MS = 25_000  # 25 seconds HTTP request timeout

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ):
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.model_name = model if model is not None else settings.GEMINI_MODEL
        self.timeout_ms = timeout_ms
        # Retained temporarily for backward compatibility; not reachable in production extraction
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
        """Extracts receipt data using Gemini Vision structured output only.

        Never falls back to regex heuristics. Returns a controlled failed result on any error.
        """
        warnings = list(initial_warnings or [])

        # If API key is not configured, return a controlled failed result
        if not self.is_available():
            warnings.append("Gemini API key is not configured.")
            return ReceiptExtractionResult(
                status="failed",
                error_code="MISSING_API_KEY",
                error_message="Gemini API key is not configured.",
                confidence=None,
                is_fallback=False,
                extraction_method="gemini_vision",
                warnings=warnings,
            )

        try:
            from google import genai  # type: ignore[import-not-found, import-untyped]
            from google.genai import types  # type: ignore[import-not-found, import-untyped]

            client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=self.timeout_ms),
            )

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
                warnings.append("Empty response received from Gemini Vision API.")
                return ReceiptExtractionResult(
                    status="failed",
                    error_code="EMPTY_RESPONSE",
                    error_message="Empty response received from Gemini Vision API.",
                    confidence=None,
                    is_fallback=False,
                    extraction_method="gemini_vision",
                    warnings=warnings,
                )

            parsed_dict = json.loads(raw_text)
            parsed_dict["is_fallback"] = False
            parsed_dict["extraction_method"] = "gemini_vision"

            # Merge warnings
            existing_warn = parsed_dict.get("warnings") or []
            parsed_dict["warnings"] = list(dict.fromkeys(warnings + existing_warn))

            # Check if document type is unsupported
            doc_type = (parsed_dict.get("document_type") or "").lower()
            if doc_type in ("unsupported", "non_receipt", "invalid"):
                parsed_dict["status"] = "failed"
                parsed_dict["error_code"] = "UNSUPPORTED_DOCUMENT"
                parsed_dict["error_message"] = "The uploaded document is not a recognized receipt."

            result = ReceiptExtractionResult.model_validate(parsed_dict)
            if result.status != "failed":
                result.validate_math_consistency()
            return result

        except Exception as e:
            is_timeout = (
                isinstance(e, TimeoutError)
                or "timeout" in type(e).__name__.lower()
                or "timedout" in type(e).__name__.lower()
                or "timeout" in str(e).lower()
                or "timed out" in str(e).lower()
            )
            err_code = "TIMEOUT" if is_timeout else "GEMINI_API_ERROR"
            err_msg = (
                "Gemini extraction timed out."
                if is_timeout
                else "Gemini Vision API extraction failed."
            )
            logger.warning("Gemini Vision extraction failed (%s): %s", err_code, type(e).__name__)
            warnings.append(f"Gemini extraction error: {err_code}")
            return ReceiptExtractionResult(
                status="failed",
                error_code=err_code,
                error_message=err_msg,
                confidence=None,
                is_fallback=False,
                extraction_method="gemini_vision",
                warnings=warnings,
            )
