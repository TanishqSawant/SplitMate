"""CLI Demo tool for SplitMate AI Receipt Extraction.

Used by Sunil (QA & Demo Lead) and Pawan for hackathon presentations and testing.

Usage:
    python demo_receipt_extractor.py --fixture 1
    python demo_receipt_extractor.py --file path/to/receipt.jpg
"""

import argparse
import json
from pathlib import Path
import sys

# Ensure backend root is in sys.path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.receipt_extractor import (
    ReceiptExtractionService,
    ReceiptExtractionError,
    ImagePreprocessor,
    PDFHandler,
)

FIXTURES_MAP = {
    1: ("receipt_01_clear_restaurant.png", "Clear Multi-Item Restaurant Bill (JPEG/PNG)"),
    2: ("receipt_02_blurry_takeout.png", "Blurry Takeout Receipt (Tests Blur Detector)"),
    3: ("receipt_03_rotated_grocery.png", "Tilted Grocery Receipt (Tests OpenCV Deskewing)"),
    4: ("receipt_04_incomplete_cafe.png", "Incomplete Cafe Receipt (Tests Null Safety)"),
    5: ("receipt_05_digital_invoice.pdf", "Digital Invoice PDF (Tests pypdfium2 Rasterizer)"),
}


def run_demo(file_path: Path):
    if not file_path.is_file():
        print(f"Error: File not found at '{file_path}'")
        sys.exit(1)

    print("=" * 70)
    print("SPLITMATE AI RECEIPT EXTRACTION DEMO")
    print("PayPal AI Hackathon 2026 | Pawan's AI Module")
    print("=" * 70)
    print(f"Target File: {file_path.name} ({round(file_path.stat().st_size / 1024, 1)} KB)")

    # 1. Initialize Service
    service = ReceiptExtractionService()

    # 2. Preprocessing Diagnostics
    file_bytes = file_path.read_bytes()
    is_pdf = PDFHandler.is_pdf(file_bytes) or file_path.suffix.lower() == ".pdf"

    if is_pdf:
        print("\n[Step 1] Document Type: PDF Document")
        pdf_handler = PDFHandler()
        pages = pdf_handler.render_pdf(file_bytes)
        print(f"  -> Rendered {len(pages)} page(s) at 2.5x scale using pypdfium2 (zero external binaries)")
        prep_img_bytes = pages[0].image_bytes
    else:
        print("\n[Step 1] Document Type: Raster Image (JPG/PNG/WEBP)")
        prep_img_bytes = file_bytes

    preprocessor = ImagePreprocessor()
    prep_result = preprocessor.preprocess(prep_img_bytes)

    print("\n[Step 2] OpenCV Preprocessing Diagnostics:")
    print(f"  * Resolution:         {prep_result.width} x {prep_result.height}")
    print(f"  * Laplacian Variance: {prep_result.blur_score:.2f} (Threshold: {preprocessor.blur_threshold})")
    print(f"  * Is Blurry?          {'YES (Warning Flagged)' if prep_result.is_blurry else 'NO (Sharp & Legible)'}")
    print(f"  * Deskew Angle:       {prep_result.skew_angle:.2f} degrees")
    if prep_result.warnings:
        print(f"  * OpenCV Warnings:    {prep_result.warnings}")

    # 3. Extraction Execution
    print("\n[Step 3] AI Vision & Structured Extraction:")
    try:
        result = service.extract_from_bytes(file_bytes, filename=file_path.name)
    except ReceiptExtractionError as e:
        print(f"  [ERROR] Validation Failure: {e}")
        return

    print(f"  * Extraction Method:  {result.extraction_method}")
    print(f"  * Is Fallback Mode?   {result.is_fallback}")
    print(f"  * Overall Confidence: {result.confidence * 100:.1f}%")
    if result.warnings:
        print(f"  * Diagnostics:        {result.warnings}")

    # 4. Display Canonical 12 Fields
    print("\n[Step 4] Canonical Extracted Fields (Pydantic Validation):")
    print(f"  1. Merchant Name:     {result.merchant_name or '(null)'}")
    print(f"  2. Merchant Address:  {result.merchant_address or '(null)'}")
    print(f"  3. Receipt Date:      {result.receipt_date or '(null)'}")
    print(f"  4. Receipt Number:    {result.receipt_number or '(null)'}")
    print(f"  5. Currency:          {result.currency or '(null)'}")
    print(f"  6. Line Items ({len(result.items)} items):")
    for idx, item in enumerate(result.items, start=1):
        print(f"     [{idx}] {item.item_name:<30} Qty: {item.quantity:<3} Unit: ${item.unit_price:<7} Total: ${item.total_price}")
    print(f"  7. Subtotal:          ${result.subtotal or '(null)'}")
    print(f"  8. Tax / GST:         ${result.tax or '(null)'}")
    print(f"  9. Discount:          ${result.discount or '(null)'}")
    print(f"  10. Gratuity / Tip:   ${result.tip or '(null)'}")
    print(f"  11. Grand Total:      ${result.final_total or '(null)'}")

    # 5. Adapter Outputs
    print("\n[Step 5] Cross-Team Integration Adapters:")
    print("  -> Payload for Tanishq's Backend (ReceiptExtractionRequest):")
    print("     " + json.dumps(result.to_backend_contract(), indent=2).replace("\n", "\n     "))
    print("\n  -> Payload for Dhruv's Frontend UI (ExtractionResult.jsx):")
    print("     " + json.dumps(result.to_frontend_contract(), indent=2).replace("\n", "\n     "))

    print("\n" + "=" * 70)
    print("EXTRACTION COMPLETED SUCCESSFULLY")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="SplitMate AI Receipt Extraction Demo")
    parser.add_argument("--fixture", type=int, choices=[1, 2, 3, 4, 5], help="Select sample fixture 1 to 5")
    parser.add_argument("--file", type=str, help="Path to custom receipt image or PDF")

    args = parser.parse_args()

    fixtures_dir = Path(__file__).parent / "tests" / "fixtures" / "receipts"

    if args.fixture:
        filename, desc = FIXTURES_MAP[args.fixture]
        print(f"\n[Selected Sample {args.fixture}] {desc}")
        file_path = fixtures_dir / filename
    elif args.file:
        file_path = Path(args.file)
    else:
        # Default to sample 1
        print("\nNo argument supplied. Running default sample 1 (Clear Restaurant Receipt).")
        print("Available options: --fixture [1-5] or --file <path>\n")
        filename, desc = FIXTURES_MAP[1]
        file_path = fixtures_dir / filename

    run_demo(file_path)


if __name__ == "__main__":
    main()

