"""OCR and Vision extraction engine abstraction.

Coordinates between:
1. Gemini Vision multimodal extraction (primary)
2. Local OCR engines (Tesseract / EasyOCR) if installed on host
3. Heuristic fallback when offline
"""

import logging
import os
import shutil
from typing import Any
from PIL import Image

from .schemas import ReceiptExtractionResult
from .llm_parser import GeminiVisionExtractor, RegexHeuristicFallback

logger = logging.getLogger(__name__)


class OCREngine:
    """Unified OCR and Vision engine for receipt text and layout extraction."""

    def __init__(
        self,
        api_key: str | None = None,
        preferred_engine: str = "gemini_vision",
    ):
        self.preferred_engine = preferred_engine
        self.gemini_extractor = GeminiVisionExtractor(api_key=api_key)
        self.fallback_parser = RegexHeuristicFallback()

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
        """Extracts text using local Tesseract if available; otherwise returns empty string."""
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
        """Processes the receipt image and extracts structured data.
        
        Strategy:
        1. If Gemini Vision is available, pass the preprocessed image and any embedded text to Gemini.
        2. If local OCR text is available and Gemini is offline, use fallback parser on local OCR text.
        3. If Gemini is offline and no local OCR exists, use fallback parser on embedded text or report degraded status.
        """
        warnings = list(initial_warnings or [])

        # Check local OCR availability
        has_local_ocr = self.is_tesseract_available()
        ocr_text = embedded_text

        if not ocr_text and has_local_ocr:
            ocr_text = self.extract_text_local_ocr(image)

        # Primary route: Gemini Vision
        if self.gemini_extractor.is_available():
            return self.gemini_extractor.extract(
                image=image,
                text_context=ocr_text,
                initial_warnings=warnings,
            )

        # If Gemini is not configured, inform the user clearly
        warnings.append("Gemini API key is not configured. Running in offline fallback mode.")
        if not has_local_ocr:
            warnings.append("Local Tesseract binary is not installed on this system.")

        return self.fallback_parser.parse_text(
            text=ocr_text,
            initial_warnings=warnings,
        )

