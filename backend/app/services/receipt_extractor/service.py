"""Main ReceiptExtractionService orchestrating the end-to-end extraction pipeline.

Coordinates:
1. Input file validation (size, MIME type, format).
2. Document conversion (PDF to high-res images via pypdfium2).
3. Image preprocessing (OpenCV blur detection, deskewing, contrast adjustment).
4. Vision & OCR extraction (Gemini Vision structured output or explicit fallback).
5. Mathematical consistency reconciliation.
6. Transformation to backend and frontend contracts.
"""

from pathlib import Path
from typing import BinaryIO
import os

from .schemas import ReceiptExtractionResult
from .preprocessor import ImagePreprocessor
from .pdf_handler import PDFHandler
from .ocr_engine import OCREngine


class ReceiptExtractionError(Exception):
    """Raised when receipt file cannot be processed or validated."""
    pass


class ReceiptExtractionService:
    """Production-grade receipt extraction service for SplitMate."""

    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
    DEFAULT_MAX_SIZE_MB = 10

    def __init__(
        self,
        api_key: str | None = None,
        max_size_mb: int = DEFAULT_MAX_SIZE_MB,
        blur_threshold: float = ImagePreprocessor.BLUR_THRESHOLD,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.preprocessor = ImagePreprocessor(blur_threshold=blur_threshold)
        self.pdf_handler = PDFHandler()
        self.ocr_engine = OCREngine(api_key=self.api_key)

    def validate_file(self, filename: str, file_size: int) -> str:
        """Validates filename extension and size bounds.
        
        Returns lowercase file extension.
        """
        if not filename:
            raise ReceiptExtractionError("Filename is required.")

        ext = Path(filename).suffix.lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            raise ReceiptExtractionError(
                f"File format '{ext}' is not supported. "
                f"Allowed formats: {', '.join(sorted(self.ALLOWED_EXTENSIONS))}"
            )

        if file_size > self.max_size_bytes:
            raise ReceiptExtractionError(
                f"File size ({round(file_size / (1024 * 1024), 2)} MB) exceeds maximum allowed "
                f"limit of {round(self.max_size_bytes / (1024 * 1024), 1)} MB."
            )

        return ext

    def extract_from_bytes(
        self,
        file_bytes: bytes,
        filename: str = "receipt.jpg",
    ) -> ReceiptExtractionResult:
        """Processes raw receipt file bytes and returns structured extraction."""
        if not file_bytes:
            raise ReceiptExtractionError("Uploaded file is empty (0 bytes).")

        ext = self.validate_file(filename, len(file_bytes))
        warnings: list[str] = []

        # ---------------------------------------------------------------------
        # Branch 1: PDF Document Processing
        # ---------------------------------------------------------------------
        if ext == ".pdf" or self.pdf_handler.is_pdf(file_bytes):
            try:
                pages = self.pdf_handler.render_pdf(file_bytes)
            except Exception as e:
                raise ReceiptExtractionError(f"Failed to process PDF receipt: {e}") from e

            # For receipts, typically page 1 has the primary invoice/bill
            primary_page = pages[0]
            embedded_text = primary_page.extracted_text

            # Run image preprocessing on rendered page
            prep_result = self.preprocessor.preprocess(primary_page.image_bytes)
            warnings.extend(prep_result.warnings)

            # Pass to OCR/Vision engine
            result = self.ocr_engine.process_receipt(
                image=prep_result.processed_image,
                embedded_text=embedded_text,
                initial_warnings=warnings,
            )
            result.validate_math_consistency()
            return result

        # ---------------------------------------------------------------------
        # Branch 2: Raster Image Processing (JPG, JPEG, PNG, WEBP)
        # ---------------------------------------------------------------------
        try:
            prep_result = self.preprocessor.preprocess(file_bytes)
        except Exception as e:
            raise ReceiptExtractionError(f"Corrupted or invalid image file: {e}") from e

        warnings.extend(prep_result.warnings)

        # Pass preprocessed image to OCR/Vision engine
        result = self.ocr_engine.process_receipt(
            image=prep_result.processed_image,
            embedded_text="",
            initial_warnings=warnings,
        )
        result.validate_math_consistency()
        return result

    def extract_from_path(self, file_path: str | Path) -> ReceiptExtractionResult:
        """Reads file from disk path and performs extraction."""
        path = Path(file_path)
        if not path.is_file():
            raise ReceiptExtractionError(f"File not found: {file_path}")

        file_bytes = path.read_bytes()
        return self.extract_from_bytes(file_bytes, filename=path.name)

