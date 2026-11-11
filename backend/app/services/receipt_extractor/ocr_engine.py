"""OCR and Vision extraction engine abstraction.

Coordinates between:
1. Gemini Vision multimodal extraction (primary and sole extraction engine)
2. Local OCR / PDF text extraction strictly as supporting preprocessing context
"""

import logging
import os
import shutil
from typing import Any
from PIL import Image

from .schemas import ReceiptExtractionResult
from .llm_parser import GeminiVisionExtractor

logger = logging.getLogger(__name__)


class OCREngine:
    """Unified OCR and Vision engine for receipt text and layout extraction.
    
    Local OCR (Tesseract / pypdfium2 embedded text) is strictly used as an input
    preprocessing and supporting step to provide text context to Gemini Vision.
    It is never used as a silent fallback substitute for failed Gemini requests.
    """

    def __init__(
        self,
        api_key: str | None = None,
        preferred_engine: str = "gemini_vision",
    ):
        self.preferred_engine = preferred_engine
        self.gemini_extractor = GeminiVisionExtractor(api_key=api_key)

    @staticmethod
    def is_tesseract_available() -> bool:
        """Verifies if the Tesseract OCR binary is actually installed and reachable on the system PATH."""
        # 1. Check system PATH
        if shutil.which("tesseract"):
            return True
        # 2. Check standard Windows installation directory
        default_win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.isfile(default_win_path):
            return True
        return False

    def extract_text_local_ocr(self, image: Image.Image) -> str:
        """Extracts text using local Tesseract if available as a supporting preprocessing step."""
        if not self.is_tesseract_available():
            logger.warning("Local Tesseract executable is not installed on this system.")
            return ""

        try:
            import pytesseract
            # If in default Windows location but not in PATH, configure it
            default_win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            if not shutil.which("tesseract") and os.path.isfile(default_win_path):
                pytesseract.pytesseract.tesseract_cmd = default_win_path

            text = pytesseract.image_to_string(image)
            return text.strip()
        except Exception as e:
            logger.warning(f"Local Tesseract OCR extraction failed: {e}")
            return ""

    def process_receipt(
        self,
        image: Image.Image,
        embedded_text: str = "",
        initial_warnings: list[str] | None = None,
    ) -> ReceiptExtractionResult:
        """Processes the receipt image and extracts structured data via Gemini Vision.
        
        Local OCR and embedded PDF text serve solely as preprocessing steps to provide
        supporting text context to Gemini Vision. If Gemini is unavailable or fails,
        the service returns a failed status with an explicit error code.
        No silent regex or OCR substitute is used.
        """
        warnings = list(initial_warnings or [])

        # Check local OCR availability (used solely as supporting text context)
        has_local_ocr = self.is_tesseract_available()
        ocr_text = embedded_text

        if not ocr_text and has_local_ocr:
            ocr_text = self.extract_text_local_ocr(image)

        # Primary and only extraction engine: Gemini Vision
        if not self.gemini_extractor.is_available():
            warnings.append("GEMINI_API_KEY environment variable is not configured.")
            return ReceiptExtractionResult(
                status="failed",
                document_type="receipt",
                is_receipt=False,
                error_code="API_KEY_MISSING",
                error_message="GEMINI_API_KEY environment variable is not configured.",
                confidence=None,
                items=[],
                missing_fields=[],
                uncertain_fields=[],
                warnings=warnings,
            )

        return self.gemini_extractor.extract(
            image=image,
            text_context=ocr_text,
            initial_warnings=warnings,
        )

