"""Generates 5 realistic receipt fixtures for SplitMate receipt extraction unit tests."""

from pathlib import Path
import io
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "receipts"
FIXTURES_DIR.mkdir(parents=True, exist_ok=True)


def get_font(size: int = 16):
    try:
        # Standard system font on Windows
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def get_bold_font(size: int = 18):
    try:
        return ImageFont.truetype("arialbd.ttf", size)
    except Exception:
        return get_font(size)


def create_receipt_image(lines: list[tuple[str, str]], width: int = 480) -> Image.Image:
    """Renders a receipt-style image with key-value or centered lines."""
    font = get_font(15)
    bold_font = get_bold_font(18)
    title_font = get_bold_font(22)

    # Estimate height
    line_h = 24
    height = len(lines) * line_h + 80

    img = Image.new("RGB", (width, height), color=(250, 250, 248))
    draw = ImageDraw.Draw(img)

    y = 30
    for style, text in lines:
        if style == "title":
            bbox = draw.textbbox((0, 0), text, font=title_font)
            w = bbox[2] - bbox[0]
            draw.text(((width - w) // 2, y), text, fill=(20, 20, 20), font=title_font)
            y += 32
        elif style == "center":
            bbox = draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
            draw.text(((width - w) // 2, y), text, fill=(80, 80, 80), font=font)
            y += line_h
        elif style == "divider":
            draw.line([(30, y + 10), (width - 30, y + 10)], fill=(180, 180, 180), width=1)
            y += 20
        elif style == "item":
            # format: "item_name|price" or "item_name|qty|price"
            parts = text.split("|")
            item_name = parts[0]
            price = parts[-1]
            draw.text((35, y), item_name, fill=(30, 30, 30), font=font)
            bbox = draw.textbbox((0, 0), price, font=font)
            pw = bbox[2] - bbox[0]
            draw.text((width - 35 - pw, y), price, fill=(30, 30, 30), font=font)
            y += line_h
        elif style == "total":
            parts = text.split("|")
            label = parts[0]
            val = parts[1]
            draw.text((35, y), label, fill=(10, 10, 10), font=bold_font)
            bbox = draw.textbbox((0, 0), val, font=bold_font)
            vw = bbox[2] - bbox[0]
            draw.text((width - 35 - vw, y), val, fill=(10, 10, 10), font=bold_font)
            y += line_h + 6

    return img


def generate_fixtures():
    # -------------------------------------------------------------------------
    # 1. Clear Restaurant Receipt (JPEG/PNG)
    # -------------------------------------------------------------------------
    lines_01 = [
        ("title", "Mario's Italian Bistro"),
        ("center", "123 Little Italy Way, New York, NY 10013"),
        ("center", "Tel: (212) 555-0199"),
        ("center", "Date: 2026-11-06   Invoice #: REC-2026-9481"),
        ("divider", ""),
        ("item", "Margherita Pizza Large|$18.00"),
        ("item", "Fettuccine Alfredo 2|$28.00"),
        ("item", "San Pellegrino Water|$4.50"),
        ("item", "Classic Tiramisu|$8.00"),
        ("divider", ""),
        ("item", "Subtotal|$58.50"),
        ("item", "Sales Tax (9%)|$5.27"),
        ("item", "Gratuity Tip|$10.00"),
        ("divider", ""),
        ("total", "TOTAL AMOUNT|$73.77"),
        ("center", "Thank you for dining with us!"),
    ]
    img_01 = create_receipt_image(lines_01)
    img_01.save(FIXTURES_DIR / "receipt_01_clear_restaurant.png")
    print("Created receipt_01_clear_restaurant.png")

    # -------------------------------------------------------------------------
    # 2. Blurry Takeout Receipt (Low Laplacian variance)
    # -------------------------------------------------------------------------
    lines_02 = [
        ("title", "Speedy Noodle Bar"),
        ("center", "45 Chinatown Ave, San Francisco, CA"),
        ("center", "Date: 2026-11-05"),
        ("divider", ""),
        ("item", "Spicy Dan Dan Noodles|$14.50"),
        ("item", "Pork Dumplings 6pc|$9.00"),
        ("item", "Iced Green Tea|$3.50"),
        ("divider", ""),
        ("item", "Subtotal|$27.00"),
        ("item", "Tax|$2.43"),
        ("total", "TOTAL|$29.43"),
    ]
    img_02 = create_receipt_image(lines_02)
    # Apply strong Gaussian Blur to trigger Laplacian variance < 80
    blurry_img = img_02.filter(ImageFilter.GaussianBlur(radius=4.5))
    blurry_img.save(FIXTURES_DIR / "receipt_02_blurry_takeout.png")
    print("Created receipt_02_blurry_takeout.png")

    # -------------------------------------------------------------------------
    # 3. Rotated Grocery Receipt (Tests deskewing)
    # -------------------------------------------------------------------------
    lines_03 = [
        ("title", "Whole Foods Market"),
        ("center", "Store #1042 - 100 Main Street"),
        ("center", "Date: 2026-11-07   Order: 44219"),
        ("divider", ""),
        ("item", "Organic Almond Milk 2|$9.98"),
        ("item", "Artisan Sourdough Loaf|$6.50"),
        ("divider", ""),
        ("item", "Subtotal|$16.48"),
        ("item", "Sales Tax|$1.48"),
        ("total", "TOTAL BALANCE|$17.96"),
    ]
    img_03 = create_receipt_image(lines_03)
    # Rotate by 8 degrees with expand
    rotated_img = img_03.rotate(8.0, resample=Image.BICUBIC, expand=True, fillcolor=(250, 250, 248))
    rotated_img.save(FIXTURES_DIR / "receipt_03_rotated_grocery.png")
    print("Created receipt_03_rotated_grocery.png")

    # -------------------------------------------------------------------------
    # 4. Incomplete Cafe Receipt (Tests null safety: no address, no tax/discount)
    # -------------------------------------------------------------------------
    lines_04 = [
        ("title", "Corner Artisan Coffee"),
        ("center", "Date: 2026-11-08"),
        ("divider", ""),
        ("item", "Double Espresso|$3.50"),
        ("item", "Butter Croissant|$4.00"),
        ("divider", ""),
        ("total", "TOTAL|$7.50"),
        ("center", "No tax applied. Cash sale."),
    ]
    img_04 = create_receipt_image(lines_04)
    img_04.save(FIXTURES_DIR / "receipt_04_incomplete_cafe.png")
    print("Created receipt_04_incomplete_cafe.png")

    # -------------------------------------------------------------------------
    # 5. Digital Invoice PDF (Tests PDF rasterization & embedded text)
    # -------------------------------------------------------------------------
    # We can create a valid single-page PDF with embedded text stream using PIL and PDF writer or minimal PDF stream
    # Let's save a clean PDF invoice using PIL's built-in PDF writer with high resolution
    lines_05 = [
        ("title", "Tech Supplies Direct"),
        ("center", "Invoice #: INV-88201"),
        ("center", "Date: 2026-11-08"),
        ("center", "Bill To: Pawan Kumar"),
        ("divider", ""),
        ("item", "USB-C Multiport Adapter 1|$39.99"),
        ("item", "Ultra HD HDMI Cable 2|$19.98"),
        ("divider", ""),
        ("item", "Subtotal|$59.97"),
        ("item", "Sales Tax (8%)|$4.80"),
        ("divider", ""),
        ("total", "TOTAL AMOUNT|$64.77"),
        ("center", "Payment Status: Paid via Card"),
    ]
    img_05 = create_receipt_image(lines_05, width=600)
    pdf_path = FIXTURES_DIR / "receipt_05_digital_invoice.pdf"
    img_05.save(pdf_path, "PDF", resolution=150.0)
    print("Created receipt_05_digital_invoice.pdf")


if __name__ == "__main__":
    generate_fixtures()

