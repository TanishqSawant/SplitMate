"""PDF handling and page rasterization using pypdfium2.

Renders receipt PDF pages into high-resolution images and extracts raw embedded text
without requiring external C binaries (such as poppler-utils).
"""

from dataclasses import dataclass
import io
from typing import BinaryIO
from PIL import Image

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None


@dataclass
class PDFPageResult:
    """Rendered page and extracted text from a PDF."""
    page_number: int
    image: Image.Image
    image_bytes: bytes
    extracted_text: str


class PDFHandler:
    """Processes PDF receipt documents into rasterized images and text."""

    def __init__(self, render_scale: float = 2.5):
        # 2.5x scale renders standard 72 DPI PDF to ~180-200 DPI suitable for vision & OCR
        self.render_scale = render_scale

    @staticmethod
    def is_pdf(file_bytes_or_stream: bytes | BinaryIO) -> bool:
        """Determines if the payload begins with PDF magic bytes (%PDF-)."""
        if isinstance(file_bytes_or_stream, bytes):
            return file_bytes_or_stream[:5] == b"%PDF-"
        pos = file_bytes_or_stream.tell()
        header = file_bytes_or_stream.read(5)
        file_bytes_or_stream.seek(pos)
        return header == b"%PDF-"

    def render_pdf(self, pdf_bytes: bytes) -> list[PDFPageResult]:
        """Renders each page of the PDF to high-res PIL Image and extracts embedded text."""
        if not self.is_pdf(pdf_bytes):
            raise ValueError("Invalid PDF format: Missing %PDF- header.")

        if pdfium is None:
            raise RuntimeError(
                "pypdfium2 is not installed. Please install pypdfium2 to enable PDF receipt processing."
            )

        try:
            doc = pdfium.PdfDocument(pdf_bytes)
        except Exception as e:
            raise ValueError(f"Failed to open or parse PDF document: {e}") from e

        results: list[PDFPageResult] = []
        for index in range(len(doc)):
            page = doc[index]

            # Extract embedded text
            textpage = page.get_textpage()
            text = textpage.get_text_range()

            # Render to bitmap at specified scale
            bitmap = page.render(scale=self.render_scale)
            pil_image = bitmap.to_pil()

            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            img_bytes = buf.getvalue()

            results.append(
                PDFPageResult(
                    page_number=index + 1,
                    image=pil_image,
                    image_bytes=img_bytes,
                    extracted_text=text.strip(),
                )
            )

        if not results:
            raise ValueError("PDF document contains 0 pages.")

        return results

