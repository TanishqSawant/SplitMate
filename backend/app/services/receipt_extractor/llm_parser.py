"""AI LLM extraction layer using Gemini structured outputs with an explicit fallback engine.

Adheres strictly to the requirements:
1. Uses Gemini structured outputs with Pydantic validation.
2. Never hallucinates missing receipt information (returns null for missing fields).
3. If fallback is triggered, explicitly marks is_fallback=True, sets low confidence,
   and details fallback reasons in warnings.
"""

import concurrent.futures
from decimal import Decimal
import json
import os
import re
from typing import Any
from PIL import Image

from .schemas import ExtractedLineItem, ReceiptExtractionResult


GEMINI_TIMEOUT_SECONDS = 30


RECEIPT_SYSTEM_PROMPT = """You are an expert financial receipt analysis AI for SplitMate.
Extract structured receipt information from the provided receipt image.

CRITICAL CLASSIFICATION & EXTRACTION RULES:
1. FIRST, CLASSIFY THE DOCUMENT:
   - is_receipt: Set to true ONLY if the document is an authentic commercial financial receipt, restaurant bill, retail bill, or business invoice representing purchased goods, dishes, or services with payable amounts.
   - Set is_receipt to false if the image contains academic notes, homework, algorithms, data structures, conversion tables (e.g. infix-to-postfix), charts, slides, code snippets, random photographs, blank images, or memes.
   - rejection_reason: If is_receipt is false, clearly explain why (e.g. 'Document is an academic conversion table, not a financial receipt.'). If is_receipt is true, set to null.
   - If is_receipt is false, you MUST return: merchant_name: null, items: [], subtotal: null, tax: null, tip: null, discount: null, final_total: null, confidence: 0.0.

2. IF AND ONLY IF is_receipt is true, extract the following fields:
   - merchant_name: Legal or commercial business name (e.g. "Mario's Bistro") or null if unreadable.
   - merchant_address: Physical street/store address, or null if absent.
   - receipt_date: Transaction date formatted as YYYY-MM-DD if recognizable, else null.
   - receipt_number: Invoice, receipt, or transaction ID, or null.
   - currency: 3-letter ISO code (e.g. USD, EUR, GBP, INR) or null if not detected. Never guess USD if unknown.
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

3. STRICT ANTI-HALLUCINATION RULE:
   - NEVER invent or fabricate missing numbers, items, or merchant names.
   - If an item or number is not explicitly visible on the receipt, output null.
   - Do NOT include 'Subtotal', 'Tax', 'Tip', 'Total', 'Cash', or 'Change' as items in the items list.
   - Only include actual products, dishes, beverages, or services purchased.
"""


class RegexHeuristicFallback:
    """Deterministic fallback parser when AI API is unavailable or offline.
    
    CRITICAL: Never silently returns incomplete regex extraction as successful AI extraction.
    Clearly marks is_fallback=True, flags confidence <= 0.35, and documents warnings.
    """

    NON_RECEIPT_PATTERNS = [
        r"\b(?:infix|postfix|prefix)\b",
        r"\b(?:parse\s*tree|expression\s*tree)\b",
        r"\b(?:stack\s*(?:pointer|contents|operation|table)|operator\s*precedence|operand|tokens?)\b",
        r"\b(?:algorithm|pseudocode|asymptotic|big-o|time\s*complexity|data\s*structures?)\b",
        r"\b(?:homework|assignment|syllabus|lecture\s*notes?|exam\s*questions?|quiz)\b",
        r"\b(?:theorem|lemma|corollary|proof\s*of|q\.e\.d\.)\b",
        r"\b(?:abstract|introduction|methodology|literature\s*review|references|bibliography)\b",
        r"\b(?:public\s+static\s+void|def\s+[a-z_]|function\s+[a-z_]|#include\s*<|import\s+sys)\b",
    ]

    FINANCIAL_PATTERNS = [
        r"\b(?:total|subtotal|sub-total|sub\s+total)\b",
        r"\b(?:tax|vat|gst|sales\s+tax|hst|cgst|sgst)\b",
        r"\b(?:balance\s*due|amount\s*due|net\s*amount|grand\s*total)\b",
        r"\b(?:cash|change|credit\s*card|debit\s*card|visa|mastercard|amex|payment)\b",
        r"\b(?:receipt|invoice|bill\s*to|bill\s*no|order\s*#|order\s*no)\b",
        r"\b(?:gratuity|tip|discount|coupon)\b",
    ]

    PRICE_PATTERN = r"(?:[$€£₹]\s*\d+[.,]\d{2}|\b\d+[.,]\d{2}\s*(?:USD|EUR|GBP|INR|Rs\.?)\b|\b\d+[.,]\d{2}\b)"
    NON_MERCHANT_WORDS = ["receipt", "invoice", "welcome", "tax", "table", "conversion", "stack", "algorithm", "lecture", "homework", "token", "chapter", "exercise", "exam", "assignment", "syllabus", "page"]

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
        r"(?:grand\s+total|total\s+amount|\b(?<!sub)(?<!sub-)(?<!sub\s)total\b|balance\s+due|amount\s+due)[\s:]*(?:[$€£₹]|Rs\.?|INR)?\s*([0-9]+[.,][0-9]{2})",
    ]

    SUBTOTAL_PATTERNS = [
        r"\b(?:subtotal|sub\s+total|sub-total|net\s+amount)\b[\s:]*(?:[$€£₹]|Rs\.?|INR)?\s*([0-9]+[.,][0-9]{2})",
    ]

    TAX_PATTERNS = [
        r"\b(?:tax|gst|vat|sales\s+tax|hst|cgst|sgst)\b(?:\s*\d+(?:\.\d+)?%)?[\s:]*(?:[$€£₹]|Rs\.?|INR)?\s*([0-9]+[.,][0-9]{2})",
    ]

    DISCOUNT_PATTERNS = [
        r"\b(?:discount|savings|coupon|promo)\b[\s:]*[-+]?(?:[$€£₹]|Rs\.?|INR)?\s*([0-9]+[.,][0-9]{2})",
    ]

    def parse_text(self, text: str, initial_warnings: list[str] | None = None) -> ReceiptExtractionResult:
        """Parses raw text via regular expressions and heuristics."""
        warnings = list(initial_warnings or [])
        warnings.append(
            "Fallback extraction used: Primary AI Vision model was offline or API key was missing. "
            "Data was parsed via regex heuristics with reduced confidence."
        )

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines or len(text.strip()) < 8:
            return ReceiptExtractionResult(
                status="failed",
                is_receipt=False,
                error_code="NO_READABLE_TEXT",
                error_message="No readable text detected in document (blank or unreadable image).",
                rejection_reason="No readable text detected in document (blank or unreadable image).",
                merchant_name=None,
                currency=None,
                items=[],
                confidence=0.0,
                is_fallback=True,
                extraction_method="regex_heuristic_fallback",
                warnings=warnings + ["No text could be extracted from document."],
            )

        # 1. Document Classification Gate: Reject academic, technical, or programming content
        for pat in self.NON_RECEIPT_PATTERNS:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                reason = f"Document contains academic, technical, or non-receipt content ('{match.group(0)}'). Rejected as not a receipt."
                return ReceiptExtractionResult(
                    status="failed",
                    is_receipt=False,
                    error_code="NON_RECEIPT_DOCUMENT",
                    error_message=reason,
                    rejection_reason=reason,
                    merchant_name=None,
                    currency=None,
                    items=[],
                    confidence=0.0,
                    is_fallback=True,
                    extraction_method="regex_heuristic_fallback",
                    warnings=warnings + [f"Non-receipt keyword detected: {match.group(0)}."],
                )

        # 2. Check for meaningful financial transaction evidence
        has_financial_term = any(re.search(pat, text, re.IGNORECASE) for pat in self.FINANCIAL_PATTERNS)
        has_prices = bool(re.search(self.PRICE_PATTERN, text))

        if not has_financial_term and not has_prices:
            reason = "Document lacks essential financial transaction indicators (no totals, line items, or prices found)."
            return ReceiptExtractionResult(
                status="failed",
                is_receipt=False,
                error_code="NON_RECEIPT_DOCUMENT",
                error_message=reason,
                rejection_reason=reason,
                merchant_name=None,
                currency=None,
                items=[],
                confidence=0.0,
                is_fallback=True,
                extraction_method="regex_heuristic_fallback",
                warnings=warnings + ["No financial transaction indicators detected."],
            )

        # 3. Merchant Name heuristic: First non-empty line without numbers, dates, or non-merchant words
        merchant_name: str | None = None
        for line in lines[:3]:
            if re.search(r"[A-Za-z]{3,}", line) and not any(kw in line.lower() for kw in self.NON_MERCHANT_WORDS):
                merchant_name = line
                break

        # 4. Currency detection (preserves None if missing)
        currency: str | None = None
        for pattern, code in self.CURRENCY_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                currency = code
                break

        if currency is None:
            warnings.append("Currency was not detected on receipt; preserved as null.")

        # 5. Date detection
        receipt_date: str | None = None
        for pattern in self.DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                receipt_date = match.group(1)
                break

        # 6. Receipt / Invoice number
        receipt_number: str | None = None
        inv_match = re.search(r"(?:invoice|receipt|order|bill)\s*(?:#|no\.?|num)?\s*[:\s]*([A-Za-z0-9\-]+)", text, re.IGNORECASE)
        if inv_match:
            receipt_number = inv_match.group(1)

        # 7. Financial totals parsing
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

        # 8. Line items parsing
        items: list[ExtractedLineItem] = []
        for line in lines:
            lower = line.lower()
            if any(skip in lower for skip in ["total", "subtotal", "tax", "vat", "gst", "tip", "balance", "visa", "mastercard", "change", "cash"]):
                continue

            item_match = re.search(r"^([A-Za-z0-9\s\-\&\'\.]+?)\s+(?:(\d+)\s+)?(?:(?:\b(?:Rs\.?|INR)\b|[$€£₹])?\s*)(\d+[.,]\d{2})$", line)
            if item_match:
                name = item_match.group(1).strip()
                qty_str = item_match.group(2)
                price_str = item_match.group(3).replace(",", ".")
                if len(name) >= 2 and not any(kw in name.lower() for kw in self.NON_MERCHANT_WORDS):
                    qty = int(qty_str) if qty_str else None
                    tot_price = Decimal(price_str)
                    unit_p = (tot_price / qty).quantize(Decimal("0.01")) if (qty is not None and qty > 0) else None
                    items.append(
                        ExtractedLineItem(
                            item_name=name,
                            quantity=qty,
                            unit_price=unit_p,
                            total_price=tot_price,
                        )
                    )

        # Confidence calculation for fallback: maximum 0.35, honest score
        confidence = 0.10
        if merchant_name:
            confidence += 0.05
        if final_total is not None:
            confidence += 0.10
        if items:
            confidence += 0.10
        confidence = min(0.35, confidence)

        result = ReceiptExtractionResult(
            is_receipt=True,
            rejection_reason=None,
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

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model_name = model or os.environ.get("GEMINI_MODEL") or self.DEFAULT_MODEL

    def is_available(self) -> bool:
        """Checks if an API key is configured for Gemini."""
        return bool(self.api_key and self.api_key.strip())

    def extract(
        self,
        image: Image.Image,
        text_context: str = "",
        initial_warnings: list[str] | None = None,
    ) -> ReceiptExtractionResult:
        """Extracts receipt data using Gemini Vision.
        
        Strict contract:
        - If API key is missing -> returns status: failed, error_code: API_KEY_MISSING.
        - If Gemini times out (>= 30s) -> returns status: failed, error_code: TIMEOUT.
        - If Gemini fails (API error, quota, network) -> returns status: failed, error_code: AI_EXTRACTION_FAILED.
        - If non-receipt document -> returns status: failed, error_code: NON_RECEIPT_DOCUMENT.
        - Never silently falls back to regex or OCR substitution.
        """
        warnings = list(initial_warnings or [])

        # If API key is not present, fail immediately
        if not self.is_available():
            warnings.append("GEMINI_API_KEY environment variable is not configured.")
            return ReceiptExtractionResult(
                status="failed",
                document_type="receipt",
                is_receipt=False,
                error_code="API_KEY_MISSING",
                error_message="GEMINI_API_KEY environment variable is not configured.",
                confidence=0.0,
                items=[],
                warnings=warnings,
            )

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)

            # Define prompt content with multimodal image
            contents: list[Any] = [image, RECEIPT_SYSTEM_PROMPT]
            if text_context:
                contents.append(f"Additional text recognized from document:\n{text_context}")

            # Execute with strict 30-second timeout
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    client.models.generate_content,
                    model=self.model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ReceiptExtractionResult,
                        temperature=0.1,  # Low temperature for deterministic, factual extraction
                    ),
                )
                try:
                    response = future.result(timeout=GEMINI_TIMEOUT_SECONDS)
                except concurrent.futures.TimeoutError:
                    return ReceiptExtractionResult(
                        status="failed",
                        is_receipt=False,
                        error_code="TIMEOUT",
                        error_message=f"Gemini Vision API request timed out after {GEMINI_TIMEOUT_SECONDS} seconds.",
                        confidence=0.0,
                        items=[],
                        warnings=warnings + [f"Gemini Vision request timed out after {GEMINI_TIMEOUT_SECONDS}s."],
                    )

            raw_text = response.text
            if not raw_text:
                return ReceiptExtractionResult(
                    status="failed",
                    is_receipt=False,
                    error_code="EMPTY_RESPONSE",
                    error_message="Empty response received from Gemini Vision API.",
                    confidence=0.0,
                    items=[],
                    warnings=warnings + ["Empty response from Gemini Vision API."],
                )

            parsed_dict = json.loads(raw_text)
            parsed_dict["is_fallback"] = False
            parsed_dict["extraction_method"] = "gemini_vision"

            # Strict handling of non-receipt classification
            if parsed_dict.get("is_receipt") is False:
                parsed_dict["status"] = "failed"
                parsed_dict["error_code"] = "NON_RECEIPT_DOCUMENT"
                parsed_dict["error_message"] = (
                    parsed_dict.get("rejection_reason")
                    or "Classified as non-receipt document by AI vision."
                )
                parsed_dict["confidence"] = 0.0
                parsed_dict["items"] = []
                parsed_dict["merchant_name"] = None
                parsed_dict["subtotal"] = None
                parsed_dict["tax"] = None
                parsed_dict["tip"] = None
                parsed_dict["discount"] = None
                parsed_dict["final_total"] = None
            else:
                # Do NOT replace missing confidence with 0.95! Calculate honest score
                if not parsed_dict.get("confidence") or parsed_dict["confidence"] <= 0.0:
                    has_items = bool(parsed_dict.get("items"))
                    has_total = parsed_dict.get("final_total") is not None
                    has_merchant = bool(parsed_dict.get("merchant_name"))
                    parsed_dict["confidence"] = round(
                        0.40
                        + (0.20 if has_items else 0.0)
                        + (0.15 if has_total else 0.0)
                        + (0.05 if has_merchant else 0.0),
                        2,
                    )

            # Merge warnings
            existing_warn = parsed_dict.get("warnings") or []
            parsed_dict["warnings"] = list(dict.fromkeys(warnings + existing_warn))

            result = ReceiptExtractionResult.model_validate(parsed_dict)
            result.validate_math_consistency()
            return result

        except Exception as e:
            return ReceiptExtractionResult(
                status="failed",
                is_receipt=False,
                error_code="AI_EXTRACTION_FAILED",
                error_message=f"Gemini Vision API extraction failed ({type(e).__name__}: {str(e)}).",
                confidence=0.0,
                items=[],
                warnings=warnings + [f"Gemini Vision API error: {str(e)}"],
            )
