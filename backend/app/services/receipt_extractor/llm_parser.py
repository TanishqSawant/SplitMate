
"""AI LLM extraction layer using Gemini structured outputs with an explicit fallback engine.

Adheres to the requirements:
1. Uses Gemini structured outputs with Pydantic validation.
2. Never hallucinates missing receipt information.
3. If fallback is triggered, marks is_fallback=True, uses low confidence,
   and documents fallback reasons in warnings.
"""

import concurrent.futures
from decimal import Decimal
import json
import logging
import os
import re
from typing import Any

from PIL import Image

from .schemas import ExtractedLineItem, ReceiptExtractionResult

logger = logging.getLogger(__name__)

GEMINI_TIMEOUT_SECONDS = 30


RECEIPT_SYSTEM_PROMPT = """You are an expert financial receipt analysis AI for SplitMate.
Extract structured receipt information from the provided receipt image.

CRITICAL CLASSIFICATION & EXTRACTION RULES:

1. FIRST, CLASSIFY THE DOCUMENT:
   - is_receipt: Set to true ONLY if the document is an authentic commercial financial receipt, restaurant bill, retail bill, or business invoice representing purchased goods, dishes, or services with payable amounts.
   - Set is_receipt to false if the image contains academic notes, homework, algorithms, data structures, conversion tables, charts, slides, code snippets, random photographs, blank images, or memes.
   - rejection_reason: If is_receipt is false, clearly explain why. If is_receipt is true, set to null.
   - If is_receipt is false, return null for all receipt fields, items as [], and confidence as 0.0.

2. IF AND ONLY IF is_receipt is true, extract:
   - merchant_name: Business name or null if unreadable.
   - merchant_address: Physical address or null if absent.
   - receipt_date: YYYY-MM-DD if recognizable, otherwise null.
   - receipt_number: Invoice, receipt, or transaction ID, or null.
   - currency: 3-letter ISO code (USD, EUR, GBP, INR, etc.) or null if not detected.
   - items: Purchased products, dishes, or services only.
       * item_name: Name of the purchased item.
       * quantity: Positive quantity or null if unstated.
       * unit_price: Non-negative decimal or null if missing.
       * total_price: Non-negative decimal or null if missing.
   - subtotal: Subtotal before taxes and discounts, or null.
   - tax: Sales tax, GST, or VAT, or null.
   - discount: Discount or coupon deduction, or null.
   - tip: Gratuity or service tip, or null.
   - final_total: Grand total payable, or null.
   - confidence: Estimated confidence between 0.0 and 1.0, or null if uncertain.

3. STRICT ANTI-HALLUCINATION RULE:
   - NEVER invent missing numbers, items, prices, quantities, currency, or merchant names.
   - If a price, quantity, or total is not explicitly visible, output null.
   - Do NOT calculate missing totals or prices.
   - Do NOT include Subtotal, Tax, Tip, Total, Cash, or Change as purchased items.
   - Only include actual products, dishes, beverages, or services.
"""


class RegexHeuristicFallback:
    """Deterministic fallback parser when the AI API is unavailable."""

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

    PRICE_PATTERN = (
        r"(?:[$€£₹]\s*\d+[.,]\d{2}"
        r"|\b\d+[.,]\d{2}\s*(?:USD|EUR|GBP|INR|Rs\.?)\b"
        r"|\b\d+[.,]\d{2}\b)"
    )

    NON_MERCHANT_WORDS = [
        "receipt", "invoice", "welcome", "tax", "table",
        "conversion", "stack", "algorithm", "lecture",
        "homework", "token", "chapter", "exercise",
        "exam", "assignment", "syllabus", "page",
    ]

    CURRENCY_PATTERNS = [
        (r"[₹]|(?:\b(?:Rs\.?|INR)\b)", "INR"),
        (r"[$]|(?:\bUSD\b)", "USD"),
        (r"[€]|(?:\bEUR\b)", "EUR"),
        (r"[£]|(?:\bGBP\b)", "GBP"),
        (r"\bCAD\b", "CAD"),
        (r"\bAUD\b", "AUD"),
    ]

    DATE_PATTERNS = [
        r"(?:^|[^\d])(\d{4}[-/]\d{1,2}[-/]\d{1,2})(?:[^\d]|$)",
        r"(?:^|[^\d])(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})(?:[^\d]|$)",
        r"\b([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b",
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

    def parse_text(
        self,
        text: str,
        initial_warnings: list[str] | None = None,
    ) -> ReceiptExtractionResult:
        """Parse receipt text using regular expressions and heuristics."""

        warnings = list(initial_warnings or [])
        warnings.append(
            "Fallback extraction used: Primary AI Vision model was offline "
            "or unavailable. Data was parsed via regex heuristics with "
            "reduced confidence."
        )

        lines = [line.strip() for line in text.splitlines() if line.strip()]

        if not lines or len(text.strip()) < 8:
            return ReceiptExtractionResult(
                status="failed",
                is_receipt=False,
                error_code="NO_READABLE_TEXT",
                error_message="No readable text detected in document.",
                rejection_reason="No readable text detected in document.",
                merchant_name=None,
                currency=None,
                items=[],
                confidence=0.0,
                is_fallback=True,
                extraction_method="regex_heuristic_fallback",
                warnings=warnings + ["No text could be extracted from document."],
            )

        # 1. Reject academic, technical, and programming documents.
        for pattern in self.NON_RECEIPT_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)

            if match:
                reason = (
                    "Document contains academic, technical, or non-receipt "
                    f"content ('{match.group(0)}'). Rejected as not a receipt."
                )

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
                    warnings=warnings + [
                        f"Non-receipt keyword detected: {match.group(0)}."
                    ],
                )

        # 2. Check financial transaction evidence.
        has_financial_term = any(
            re.search(pattern, text, re.IGNORECASE)
            for pattern in self.FINANCIAL_PATTERNS
        )

        has_prices = bool(re.search(self.PRICE_PATTERN, text))

        if not has_financial_term and not has_prices:
            reason = (
                "Document lacks essential financial transaction indicators "
                "(no totals, line items, or prices found)."
            )

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
                warnings=warnings + [
                    "No financial transaction indicators detected."
                ],
            )

        # 3. Merchant name heuristic.
        merchant_name: str | None = None

        for line in lines[:3]:
            if (
                re.search(r"[A-Za-z]{3,}", line)
                and not any(
                    keyword in line.lower()
                    for keyword in self.NON_MERCHANT_WORDS
                )
            ):
                merchant_name = line
                break

        # 4. Currency detection.
        currency: str | None = None

        for pattern, code in self.CURRENCY_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                currency = code
                break

        if currency is None:
            warnings.append(
                "Currency was not detected on receipt; preserved as null."
            )

        # 5. Date detection.
        receipt_date: str | None = None

        for pattern in self.DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)

            if match:
                receipt_date = match.group(1)
                break

        # 6. Receipt / invoice number.
        receipt_number: str | None = None

        invoice_match = re.search(
            r"(?:invoice|receipt|order|bill)\s*"
            r"(?:#|no\.?|num)?\s*[:\s]*([A-Za-z0-9\-]+)",
            text,
            re.IGNORECASE,
        )

        if invoice_match:
            receipt_number = invoice_match.group(1)

        # 7. Financial totals.
        def extract_amount(patterns: list[str]) -> Decimal | None:
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)

                if match:
                    raw = match.group(1).replace(",", ".")

                    try:
                        return Decimal(raw)
                    except Exception:
                        continue

            return None

        subtotal = extract_amount(self.SUBTOTAL_PATTERNS)
        tax = extract_amount(self.TAX_PATTERNS)
        discount = extract_amount(self.DISCOUNT_PATTERNS)
        final_total = extract_amount(self.TOTAL_PATTERNS)

        # 8. Line items parsing.
        logger.debug(
            "RegexFallback parsing %d lines; preview: %s",
            len(lines),
            text[:300].replace("\n", " | "),
        )

        items: list[ExtractedLineItem] = []

        skip_exact = [
            "subtotal", "sub total", "sub-total", "tax",
            "sales tax", "vat", "gst", "hst", "cgst", "sgst",
            "tip", "gratuity", "balance", "amount due",
            "balance due", "payment method", "auth code",
            "approval code", "visa", "mastercard", "amex",
            "discover", "apple pay", "google pay", "cash",
            "change", "thank you", "thanks for",
            "have a great", "have a nice", "store:", "date:",
            "receipt #", "invoice #", "order #",
        ]

        curr = r"(?:[$€£₹]|Rs\.?|INR)?"
        num = r"\d+[.,]\d{2}"

        for line in lines:
            lower = line.lower()

            if any(keyword in lower for keyword in skip_exact):
                continue

            # Skip table headers.
            if (
                ("item" in lower or "description" in lower)
                and ("price" in lower or "qty" in lower or "total" in lower)
            ):
                continue

            # Skip summary total lines.
            if re.search(r"\b(?:grand\s+total|total)\b", lower):
                continue

            item_obj = None

            # Case 1: Two prices at the end of the line.
            # Example: Organic Bananas 1.00 lb $1.29 $1.29
            m2 = re.search(
                rf"^(.+?)\s+{curr}\s*({num})\s+{curr}\s*({num})$",
                line,
                re.IGNORECASE,
            )

            if m2:
                raw_name = m2.group(1).strip()
                price1_str = m2.group(2).replace(",", ".")
                price2_str = m2.group(3).replace(",", ".")

                unit_p = Decimal(price1_str)
                tot_p = Decimal(price2_str)
                qty = 1

                if not raw_name.endswith(")"):
                    for pattern in [
                        r"^(.*?)\s+(\d+(?:\.\d+)?)\s+(?:lb|1b|ea|kg|g|oz|pk|ct|[a-zA-Z]{1,4})$",
                        r"^(.*?)\s+(\d+(?:\.\d+)?)$",
                    ]:
                        quantity_match = re.search(
                            pattern,
                            raw_name,
                            re.IGNORECASE,
                        )

                        if (
                            quantity_match
                            and len(quantity_match.group(1).strip()) >= 2
                        ):
                            raw_name = quantity_match.group(1).strip()

                            try:
                                value = float(quantity_match.group(2))
                                qty = max(1, int(round(value)))
                            except (ValueError, TypeError):
                                pass

                            break

                if qty > 1 and unit_p > 0 and tot_p == unit_p:
                    qty = 1

                if len(raw_name) >= 2:
                    item_obj = ExtractedLineItem(
                        item_name=raw_name,
                        quantity=qty,
                        unit_price=unit_p,
                        total_price=tot_p,
                    )

            # Case 2: Single price at the end of the line.
            if not item_obj:
                m1 = re.search(
                    rf"^(.+?)\s+(?:(\d+)\s+)?{curr}\s*({num})$",
                    line,
                    re.IGNORECASE,
                )

                if m1:
                    raw_name = m1.group(1).strip()
                    raw_qty = m1.group(2)
                    price_str = m1.group(3).replace(",", ".")

                    qty = int(raw_qty) if raw_qty else 1
                    tot_p = Decimal(price_str)

                    unit_p = (
                        tot_p / qty
                    ).quantize(Decimal("0.01"))

                    if not raw_name.endswith(")") and not raw_qty:
                        for pattern in [
                            r"^(.*?)\s+(\d+(?:\.\d+)?)\s+(?:lb|1b|ea|kg|g|oz|pk|ct|[a-zA-Z]{1,4})$",
                            r"^(.*?)\s+(\d+(?:\.\d+)?)$",
                        ]:
                            quantity_match = re.search(
                                pattern,
                                raw_name,
                                re.IGNORECASE,
                            )

                            if (
                                quantity_match
                                and len(quantity_match.group(1).strip()) >= 2
                            ):
                                raw_name = quantity_match.group(1).strip()

                                try:
                                    value = float(quantity_match.group(2))
                                    qty = max(1, int(round(value)))

                                    unit_p = (
                                        tot_p / qty
                                    ).quantize(Decimal("0.01"))
                                except (ValueError, TypeError):
                                    pass

                                break

                    if len(raw_name) >= 2:
                        item_obj = ExtractedLineItem(
                            item_name=raw_name,
                            quantity=qty,
                            unit_price=unit_p,
                            total_price=tot_p,
                        )

            if item_obj:
                items.append(item_obj)

        # 9. Confidence calculation for fallback.
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
    """Extract structured receipt data using Gemini Vision."""

    DEFAULT_MODEL = "gemini-2.5-flash"
    FALLBACK_MODEL = "gemini-1.5-flash"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.model_name = (
            model
            or os.environ.get("GEMINI_MODEL")
            or self.DEFAULT_MODEL
        )

        # Initialize offline fallback parser.
        self.fallback_parser = RegexHeuristicFallback()

    def is_available(self) -> bool:
        """Check whether a Gemini API key is configured."""
        return bool(self.api_key and self.api_key.strip())

    def extract(
        self,
        image: Image.Image,
        text_context: str = "",
        initial_warnings: list[str] | None = None,
    ) -> ReceiptExtractionResult:
        """Extract receipt data using Gemini Vision.

        If Gemini is unavailable or fails, use the offline regex fallback.
        """

        warnings = list(initial_warnings or [])

        if not self.is_available():
            warnings.append(
                "GEMINI_API_KEY environment variable is not configured."
            )

            return self.fallback_parser.parse_text(
                text_context,
                initial_warnings=warnings,
            )

        try:
            from google import genai
            from google.genai import types

            http_options = types.HttpOptions(timeout=30000)

            client = genai.Client(
                api_key=self.api_key,
                http_options=http_options,
            )

            contents: list[Any] = [
                image,
                RECEIPT_SYSTEM_PROMPT,
            ]

            if text_context:
                contents.append(
                    "Additional text recognized from document:\n"
                    + text_context
                )

            executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=1
            )

            future = executor.submit(
                client.models.generate_content,
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ReceiptExtractionResult,
                    temperature=0.1,
                    http_options=http_options,
                ),
            )

            try:
                response = future.result(
                    timeout=GEMINI_TIMEOUT_SECONDS
                )

            except concurrent.futures.TimeoutError:
                executor.shutdown(
                    wait=False,
                    cancel_futures=True,
                )

                warnings.append(
                    f"Gemini Vision request timed out after "
                    f"{GEMINI_TIMEOUT_SECONDS}s."
                )

                return self.fallback_parser.parse_text(
                    text_context,
                    initial_warnings=warnings,
                )

            finally:
                executor.shutdown(
                    wait=False,
                    cancel_futures=True,
                )

            raw_text = response.text if response else None

            if not raw_text:
                warnings.append(
                    "Empty response received from Gemini Vision API."
                )

                return self.fallback_parser.parse_text(
                    text_context,
                    initial_warnings=warnings,
                )

            try:
                parsed_dict = json.loads(raw_text)

            except (ValueError, TypeError):
                warnings.append(
                    "Invalid JSON response received from Gemini Vision API."
                )

                return self.fallback_parser.parse_text(
                    text_context,
                    initial_warnings=warnings,
                )

            parsed_dict["is_fallback"] = False
            parsed_dict["extraction_method"] = "gemini_vision"

            # Handle non-receipt documents.
            if parsed_dict.get("is_receipt") is False:
                parsed_dict["status"] = "failed"
                parsed_dict["document_type"] = "non_receipt"
                parsed_dict["error_code"] = "NON_RECEIPT_DOCUMENT"

                parsed_dict["error_message"] = (
                    parsed_dict.get("rejection_reason")
                    or "Classified as non-receipt document by AI vision."
                )

                parsed_dict["confidence"] = 0.0
                parsed_dict["items"] = []
                parsed_dict["merchant_name"] = None
                parsed_dict["merchant_address"] = None
                parsed_dict["receipt_date"] = None
                parsed_dict["receipt_number"] = None
                parsed_dict["currency"] = None
                parsed_dict["subtotal"] = None
                parsed_dict["tax"] = None
                parsed_dict["tip"] = None
                parsed_dict["discount"] = None
                parsed_dict["final_total"] = None
                parsed_dict["missing_fields"] = []
                parsed_dict["uncertain_fields"] = []

            else:
                # Do not fabricate missing confidence.
                raw_conf = parsed_dict.get("confidence")

                if raw_conf is not None:
                    try:
                        value = float(raw_conf)

                        parsed_dict["confidence"] = (
                            round(value, 2)
                            if 0.0 <= value <= 1.0
                            else None
                        )

                    except (ValueError, TypeError):
                        parsed_dict["confidence"] = None

                else:
                    parsed_dict["confidence"] = None

            # Merge warnings without duplicates.
            existing_warnings = parsed_dict.get("warnings") or []

            parsed_dict["warnings"] = list(
                dict.fromkeys(warnings + existing_warnings)
            )

            result = ReceiptExtractionResult.model_validate(
                parsed_dict
            )

            result.validate_math_consistency()

            return result

        except Exception as e:
            # Handle Gemini API failures and use offline fallback.
            err_str = str(e)

            if (
                "403" in err_str
                or "PERMISSION_DENIED" in err_str
                or "billing" in err_str.lower()
            ):
                api_warning = (
                    "Gemini Vision API returned 403 PERMISSION_DENIED. "
                    "The free tier is unavailable for this Google Cloud "
                    "project; billing would be required. "
                    "Using offline OCR + regex extraction instead."
                )

            elif (
                "429" in err_str
                or "quota" in err_str.lower()
                or "resource_exhausted" in err_str.lower()
            ):
                api_warning = (
                    "Gemini Vision API quota or rate limit exceeded. "
                    "Using offline OCR + regex extraction."
                )

            elif (
                "getaddrinfo" in err_str
                or "ConnectError" in err_str
                or "network" in err_str.lower()
            ):
                api_warning = (
                    "Gemini Vision API is unreachable "
                    f"(network error: {type(e).__name__}). "
                    "Using offline OCR + regex extraction."
                )

            else:
                api_warning = (
                    "Gemini Vision API extraction failed "
                    f"({type(e).__name__}: {err_str}). "
                    "Using offline fallback parser."
                )

            logger.warning(api_warning)

            warnings.append(api_warning)

            return self.fallback_parser.parse_text(
                text_context,
                initial_warnings=warnings,
            )
