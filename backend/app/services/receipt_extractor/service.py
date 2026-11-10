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
    GEMINI_TIMEOUT_SECONDS = 30

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

    def validate_receipt(self, result: ReceiptExtractionResult) -> None:
        """Validates that extraction result qualifies as a legitimate financial receipt.
        
        Raises ReceiptExtractionError if the document was classified as a non-receipt
        or has insufficient confidence.
        """
        if not result.is_receipt or result.status == "failed":
            raise ReceiptExtractionError(
                result.rejection_reason or result.error_message or "Uploaded document does not appear to be a valid financial receipt or invoice."
            )

        if result.confidence < 0.20 and not result.items:
            raise ReceiptExtractionError(
                "Document extraction confidence is insufficient and no line items were identified. "
                "Please upload a clear, legible receipt."
            )

    def extract_from_bytes(
        self,
        file_bytes: bytes,
        filename: str = "receipt.jpg",
        reject_non_receipt: bool = False,
        raise_on_error: bool = False,
    ) -> ReceiptExtractionResult:
        """Processes raw receipt file bytes and returns structured extraction.
        
        If reject_non_receipt or raise_on_error is True, raises ReceiptExtractionError
        on failures, unsupported formats, or non-receipt captures.
        Otherwise returns a failed ReceiptExtractionResult with error_code and error_message.
        """
        if not file_bytes:
            msg = "Uploaded file is empty (0 bytes)."
            if raise_on_error or reject_non_receipt:
                raise ReceiptExtractionError(msg)
            return ReceiptExtractionResult(
                status="failed",
                is_receipt=False,
                error_code="EMPTY_FILE",
                error_message=msg,
                confidence=0.0,
                items=[],
                warnings=[msg],
            )

        if not filename:
            msg = "Filename is required."
            if raise_on_error or reject_non_receipt:
                raise ReceiptExtractionError(msg)
            return ReceiptExtractionResult(
                status="failed",
                is_receipt=False,
                error_code="INVALID_FILENAME",
                error_message=msg,
                confidence=0.0,
                items=[],
                warnings=[msg],
            )

        ext = Path(filename).suffix.lower()
        if ext not in self.ALLOWED_EXTENSIONS:
            msg = f"File format '{ext}' is not supported. Allowed formats: {', '.join(sorted(self.ALLOWED_EXTENSIONS))}"
            if raise_on_error or reject_non_receipt:
                raise ReceiptExtractionError(msg)
            return ReceiptExtractionResult(
                status="failed",
                is_receipt=False,
                error_code="UNSUPPORTED_FORMAT",
                error_message=msg,
                confidence=0.0,
                items=[],
                warnings=[msg],
            )

        if len(file_bytes) > self.max_size_bytes:
            msg = (
                f"File size ({round(len(file_bytes) / (1024 * 1024), 2)} MB) exceeds maximum allowed "
                f"limit of {round(self.max_size_bytes / (1024 * 1024), 1)} MB."
            )
            if raise_on_error or reject_non_receipt:
                raise ReceiptExtractionError(msg)
            return ReceiptExtractionResult(
                status="failed",
                is_receipt=False,
                error_code="FILE_TOO_LARGE",
                error_message=msg,
                confidence=0.0,
                items=[],
                warnings=[msg],
            )

        warnings: list[str] = []

        # ---------------------------------------------------------------------
        # Branch 1: PDF Document Processing
        # ---------------------------------------------------------------------
        if ext == ".pdf" or self.pdf_handler.is_pdf(file_bytes):
            try:
                pages = self.pdf_handler.render_pdf(file_bytes)
            except Exception as e:
                msg = f"Failed to process PDF receipt: {e}"
                if raise_on_error or reject_non_receipt:
                    raise ReceiptExtractionError(msg) from e
                return ReceiptExtractionResult(
                    status="failed",
                    is_receipt=False,
                    error_code="CORRUPTED_PDF",
                    error_message=msg,
                    confidence=0.0,
                    items=[],
                    warnings=[msg],
                )

            primary_page = pages[0]
            embedded_text = primary_page.extracted_text

            prep_result = self.preprocessor.preprocess(primary_page.image_bytes)
            warnings.extend(prep_result.warnings)

            result = self.ocr_engine.process_receipt(
                image=prep_result.processed_image,
                embedded_text=embedded_text,
                initial_warnings=warnings,
            )
            result.validate_math_consistency()
            if reject_non_receipt:
                self.validate_receipt(result)
            return result

        # ---------------------------------------------------------------------
        # Branch 2: Raster Image Processing (JPG, JPEG, PNG, WEBP)
        # ---------------------------------------------------------------------
        try:
            prep_result = self.preprocessor.preprocess(file_bytes)
        except Exception as e:
            msg = f"Corrupted or invalid image file: {e}"
            if raise_on_error or reject_non_receipt:
                raise ReceiptExtractionError(msg) from e
            return ReceiptExtractionResult(
                status="failed",
                is_receipt=False,
                error_code="CORRUPTED_IMAGE",
                error_message=msg,
                confidence=0.0,
                items=[],
                warnings=[msg],
            )

        warnings.extend(prep_result.warnings)

        result = self.ocr_engine.process_receipt(
            image=prep_result.processed_image,
            embedded_text="",
            initial_warnings=warnings,
        )
        result.validate_math_consistency()
        if reject_non_receipt:
            self.validate_receipt(result)
        return result

    def extract_from_path(
        self,
        file_path: str | Path,
        reject_non_receipt: bool = False,
        raise_on_error: bool = False,
    ) -> ReceiptExtractionResult:
        """Reads file from disk path and performs extraction."""
        path = Path(file_path)
        if not path.is_file():
            raise ReceiptExtractionError(f"File not found: {file_path}")

        file_bytes = path.read_bytes()
        return self.extract_from_bytes(
            file_bytes,
            filename=path.name,
            reject_non_receipt=reject_non_receipt,
            raise_on_error=raise_on_error,
        )

