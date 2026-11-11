
"""OCR and Vision extraction engine abstraction.

Coordinates between:
1. Gemini Vision multimodal extraction (primary extraction engine).
2. Local Tesseract / RapidOCR as supporting preprocessing.
3. Offline regex fallback when Gemini is unavailable.
"""

import logging
import os
import re
import shutil

from PIL import Image

from .schemas import ReceiptExtractionResult
from .llm_parser import GeminiVisionExtractor

logger = logging.getLogger(__name__)


def _split_camel_merged_token(token: str) -> str:
    """Insert spaces where RapidOCR merged adjacent CamelCase words.

    Example:
        OrganicBananas -> Organic Bananas
        WholeMilk -> Whole Milk

    All-uppercase tokens and tokens containing spaces are preserved.
    """
    if " " in token or token.isupper():
        return token

    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", token)


class OCREngine:
    """Unified OCR and Vision engine for receipt extraction.

    Gemini Vision is the primary extraction engine.

    Local OCR is used to provide supporting text context.
    If Gemini is unavailable, GeminiVisionExtractor uses its
    configured offline regex fallback.
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
        """Check whether the Tesseract executable is installed."""

        if shutil.which("tesseract"):
            return True

        default_win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

        return os.path.isfile(default_win_path)

    def extract_text_local_ocr(self, image: Image.Image) -> str:
        """Extract supporting text using local Tesseract OCR."""

        if not self.is_tesseract_available():
            logger.warning(
                "Local Tesseract executable is not installed."
            )
            return ""

        try:
            import pytesseract

            default_win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

            if (
                not shutil.which("tesseract")
                and os.path.isfile(default_win_path)
            ):
                pytesseract.pytesseract.tesseract_cmd = default_win_path

            text = pytesseract.image_to_string(image)

            return text.strip()

        except Exception as exc:
            logger.warning(
                "Local Tesseract OCR extraction failed: %s",
                exc,
            )
            return ""

    @staticmethod
    def is_rapidocr_available() -> bool:
        """Check whether RapidOCR is installed."""

        try:
            import rapidocr_onnxruntime  # noqa: F401
            return True

        except ImportError:
            return False

    def extract_text_rapidocr(self, image: Image.Image) -> str:
        """Extract text using the offline RapidOCR ONNX model.

        Groups detected words into lines using their Y-centres
        and sorts words from left to right.
        """

        try:
            import numpy as np
            from rapidocr_onnxruntime import RapidOCR

            engine = RapidOCR()

            img_arr = np.array(image.convert("RGB"))

            result, _ = engine(img_arr)

            if not result:
                logger.warning(
                    "RapidOCR returned no detections for this image."
                )
                return ""

            # Group bounding boxes into lines.
            lines_dict: dict[float, list[tuple[float, str]]] = {}

            for box, text, _score in result:
                y_center = sum(point[1] for point in box) / 4.0
                x_min = min(point[0] for point in box)

                matched_y: float | None = None

                for y_key in lines_dict:
                    if abs(y_key - y_center) < 14:
                        matched_y = y_key
                        break

                if matched_y is None:
                    matched_y = y_center
                    lines_dict[matched_y] = []

                lines_dict[matched_y].append((x_min, text))

            # Reconstruct text lines.
            reconstructed: list[str] = []

            for y_key in sorted(lines_dict.keys()):
                row = sorted(
                    lines_dict[y_key],
                    key=lambda item: item[0],
                )

                reconstructed.append(
                    " ".join(
                        _split_camel_merged_token(token)
                        for _, token in row
                    )
                )

            extracted = "\n".join(reconstructed)

            logger.info(
                "RapidOCR extracted %d lines of text.",
                len(reconstructed),
            )

            return extracted

        except Exception as exc:
            logger.warning(
                "RapidOCR extraction failed: %s",
                exc,
            )
            return ""

    def process_receipt(
        self,
        image: Image.Image,
        embedded_text: str = "",
        initial_warnings: list[str] | None = None,
    ) -> ReceiptExtractionResult:
        """Process a receipt image and extract structured information.

        Strategy:
        1. Use embedded PDF text if available.
        2. Otherwise try local Tesseract OCR.
        3. If Tesseract provides no text, try RapidOCR.
        4. Send the image and extracted text to Gemini Vision.
        5. If Gemini is unavailable or fails, use its offline
           regex fallback with the available OCR text.
        """

        warnings = list(initial_warnings or [])

        # ---------------------------------------------------------
        # 1. Start with embedded PDF text, if available.
        # ---------------------------------------------------------
        ocr_text = (embedded_text or "").strip()

        if ocr_text:
            warnings.append(
                "Text extracted from embedded PDF content."
            )

        # ---------------------------------------------------------
        # 2. Try Tesseract OCR.
        # ---------------------------------------------------------
        if not ocr_text:
            if self.is_tesseract_available():
                ocr_text = self.extract_text_local_ocr(image)

                if ocr_text:
                    warnings.append(
                        "Text pre-extracted using local Tesseract OCR."
                    )

            else:
                warnings.append(
                    "Tesseract OCR binary is not installed."
                )

        # ---------------------------------------------------------
        # 3. Try RapidOCR if Tesseract produced no text.
        # ---------------------------------------------------------
        if not ocr_text:
            if self.is_rapidocr_available():
                ocr_text = self.extract_text_rapidocr(image)

                if ocr_text:
                    warnings.append(
                        "Text extracted using RapidOCR offline ONNX model."
                    )

            else:
                warnings.append(
                    "RapidOCR package is not installed. "
                    "Install it using: pip install rapidocr-onnxruntime"
                )

        # ---------------------------------------------------------
        # 4. Primary extraction: Gemini Vision.
        #
        # GeminiVisionExtractor handles missing API keys and
        # API failures by invoking RegexHeuristicFallback.
        # ---------------------------------------------------------
        try:
            return self.gemini_extractor.extract(
                image=image,
                text_context=ocr_text,
                initial_warnings=warnings,
            )

        except Exception as exc:
            logger.exception(
                "Receipt extraction engine failed unexpectedly."
            )

            return ReceiptExtractionResult(
                status="failed",
                document_type="receipt",
                is_receipt=False,
                error_code="AI_EXTRACTION_FAILED",
                error_message=(
                    "Receipt extraction failed unexpectedly."
                ),
                confidence=None,
                items=[],
                missing_fields=[],
                uncertain_fields=[],
                warnings=warnings + [
                    f"Unexpected extraction error: {type(exc).__name__}: {exc}"
                ],
            )
