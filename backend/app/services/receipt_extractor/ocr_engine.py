"""OCR and Vision extraction engine abstraction.

Coordinates between:
1. Gemini Vision multimodal extraction (primary)
2. Local OCR engines (Tesseract / EasyOCR) if installed on host
3. Heuristic fallback when offline
"""

import logging
import os
import re
import shutil
from typing import Any
from PIL import Image

from .schemas import ReceiptExtractionResult
from .llm_parser import GeminiVisionExtractor, RegexHeuristicFallback

logger = logging.getLogger(__name__)


def _split_camel_merged_token(token: str) -> str:
    """Insert spaces where RapidOCR merged adjacent words into CamelCase.

    For example: ``OrganicBananas`` → ``Organic Bananas``
                 ``WholeMilk``     → ``Whole Milk``
    Preserves intentional brand names like ``FreshMart`` or ``PayPal``
    because a space between them is harmless for the regex parser.
    Does NOT affect all-caps tokens (e.g., ``TAX``, ``USD``) or tokens
    that already contain spaces.
    """
    # Only process if no space present and the token is not all-uppercase
    if " " in token or token.isupper():
        return token
    # Insert a space before each uppercase letter that follows a lowercase letter
    # e.g. "OrganicBananas" → "Organic Bananas"
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", token)


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

    @staticmethod
    def is_rapidocr_available() -> bool:
        """Checks whether the rapidocr-onnxruntime package is importable."""
        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True
        except ImportError:
            return False

    def extract_text_rapidocr(self, image: Image.Image) -> str:
        """Extracts text using RapidOCR ONNX model — works fully offline, no system binaries needed.

        RapidOCR returns a list of (bounding_box, text, confidence) tuples.
        We reconstruct lines by grouping detections that share a similar Y-centre coordinate
        and sort tokens left-to-right within each line.
        """
        try:
            import numpy as np
            from rapidocr_onnxruntime import RapidOCR

            engine = RapidOCR()
            img_arr = np.array(image.convert("RGB"))
            result, _ = engine(img_arr)
            if not result:
                logger.warning("RapidOCR returned no detections for this image.")
                return ""

            # Group bounding boxes into lines by Y-centre proximity (threshold: 14 px)
            lines_dict: dict[float, list[tuple[float, str]]] = {}
            for box, text, _score in result:
                y_center = sum(pt[1] for pt in box) / 4.0
                x_min = min(pt[0] for pt in box)
                matched_y: float | None = None
                for y_key in lines_dict:
                    if abs(y_key - y_center) < 14:
                        matched_y = y_key
                        break
                if matched_y is None:
                    matched_y = y_center
                    lines_dict[matched_y] = []
                lines_dict[matched_y].append((x_min, text))

            reconstructed: list[str] = []
            for y_key in sorted(lines_dict.keys()):
                row = sorted(lines_dict[y_key], key=lambda t: t[0])
                # Split CamelCase merges produced by RapidOCR (e.g. "OrganicBananas" → "Organic Bananas")
                reconstructed.append(" ".join(_split_camel_merged_token(tok) for _, tok in row))

            extracted = "\n".join(reconstructed)
            logger.info("RapidOCR extracted %d lines of text.", len(reconstructed))
            return extracted

        except Exception as exc:
            logger.warning("RapidOCR extraction failed: %s", exc)
            return ""

    def process_receipt(
        self,
        image: Image.Image,
        embedded_text: str = "",
        initial_warnings: list[str] | None = None,
    ) -> ReceiptExtractionResult:
        """Processes the receipt image and extracts structured data.

        Strategy:
        1. Try Gemini Vision (primary) if API key is configured.
        2. If Gemini is offline/unavailable, attempt local text extraction:
           a. Tesseract (if installed on the host system).
           b. RapidOCR ONNX (installed Python package — offline capable).
        3. Feed extracted text to RegexHeuristicFallback.
        4. If no text at all, return a FAILED result with clear warnings.
        """
        warnings = list(initial_warnings or [])

        # ------------------------------------------------------------------ #
        # 1. Build local OCR text (used as context for Gemini or as sole input)
        # ------------------------------------------------------------------ #
        ocr_text = embedded_text

        if not ocr_text and self.is_tesseract_available():
            ocr_text = self.extract_text_local_ocr(image)
            if ocr_text:
                warnings.append("Text pre-extracted via local Tesseract OCR.")

        if not ocr_text and self.is_rapidocr_available():
            ocr_text = self.extract_text_rapidocr(image)
            if ocr_text:
                warnings.append("Text extracted via RapidOCR (offline ONNX model).")

        # ------------------------------------------------------------------ #
        # 2. Primary route: Gemini Vision
        # ------------------------------------------------------------------ #
        if self.gemini_extractor.is_available():
            return self.gemini_extractor.extract(
                image=image,
                text_context=ocr_text,
                initial_warnings=warnings,
            )

        # ------------------------------------------------------------------ #
        # 3. Offline fallback: regex heuristic on whatever text we could get
        # ------------------------------------------------------------------ #
        warnings.append("Gemini Vision API key is not configured. Running in offline fallback mode.")
        if not self.is_tesseract_available():
            warnings.append("Tesseract OCR binary is not installed on this system.")
        if not self.is_rapidocr_available():
            warnings.append("RapidOCR package is not installed (pip install rapidocr-onnxruntime).")

        return self.fallback_parser.parse_text(
            text=ocr_text,
            initial_warnings=warnings,
        )

