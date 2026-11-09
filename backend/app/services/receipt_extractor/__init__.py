"""AI Receipt Extraction module for SplitMate.

Provides:
- ReceiptExtractionService: Unified service for receipt OCR and AI extraction.
- ReceiptExtractionResult: Canonical Pydantic model containing all 12 receipt fields.
- ExtractedLineItem: Pydantic model for individual itemized line items.
- ImagePreprocessor: OpenCV blur detection, deskewing, and image enhancement.
- PDFHandler: Pure-Python PDF rasterization via pypdfium2.
- ReceiptExtractionError: Domain exception for extraction and validation failures.
"""

from .schemas import ExtractedLineItem, ReceiptExtractionResult
from .service import ReceiptExtractionError, ReceiptExtractionService
from .preprocessor import ImagePreprocessor, PreprocessingResult
from .pdf_handler import PDFHandler, PDFPageResult
from .ocr_engine import OCREngine
from .llm_parser import GeminiVisionExtractor, RegexHeuristicFallback

__all__ = [
    "ReceiptExtractionService",
    "ReceiptExtractionResult",
    "ExtractedLineItem",
    "ReceiptExtractionError",
    "ImagePreprocessor",
    "PreprocessingResult",
    "PDFHandler",
    "PDFPageResult",
    "OCREngine",
    "GeminiVisionExtractor",
    "RegexHeuristicFallback",
]

