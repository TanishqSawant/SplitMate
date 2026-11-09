"""Tests for the receipts API — including Fix 2 (magic-byte validation) and Fix 3 (AI key auth)."""

import io

from tests.conftest import (
    TEST_INTERNAL_SERVICE_SECRET,
    VALID_JPEG_BYTES,
    VALID_PNG_BYTES,
    VALID_WEBP_BYTES,
    VALID_PDF_BYTES,
)

AI_KEY_HEADER = {"X-Internal-Service-Key": TEST_INTERNAL_SERVICE_SECRET}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upload(client, filename: str, content: bytes, mime: str = "application/octet-stream"):
    return client.post(
        "/api/receipts/upload",
        files={"file": (filename, io.BytesIO(content), mime)},
    )


def _extraction_payload(**overrides):
    base = {
        "merchant_name": "Mario's Pizzeria",
        "currency": "USD",
        "subtotal": "45.50",
        "tax": "3.64",
        "total": "49.14",
        "items": [
            {
                "item_name": "Margherita Pizza",
                "quantity": 1,
                "unit_price": "18.00",
                "total_price": "18.00",
            },
            {
                "item_name": "Pasta Carbonara",
                "quantity": 2,
                "unit_price": "13.75",
                "total_price": "27.50",
            },
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Original upload tests (Fix 2 — updated to use valid bytes)
# ---------------------------------------------------------------------------

def test_upload_receipt(client):
    """Fix 2: Valid JPEG upload succeeds."""
    response = _upload(client, "receipt.jpg", VALID_JPEG_BYTES, "image/jpeg")
    assert response.status_code == 201
    data = response.json()
    assert data["original_filename"] == "receipt.jpg"
    assert data["extraction_status"] == "pending"
    assert "id" in data


def test_upload_receipt_invalid_type(client):
    """Extension not in the allowed list is still rejected."""
    response = _upload(client, "receipt.txt", b"not a valid file", "text/plain")
    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]


def test_get_receipt(client):
    upload_resp = _upload(client, "receipt.png", VALID_PNG_BYTES, "image/png")
    assert upload_resp.status_code == 201
    receipt_id = upload_resp.json()["id"]

    response = client.get(f"/api/receipts/{receipt_id}")
    assert response.status_code == 200
    assert response.json()["original_filename"] == "receipt.png"


def test_get_receipt_not_found(client):
    response = client.get("/api/receipts/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Fix 2: Magic-byte content validation tests
# ---------------------------------------------------------------------------

def test_upload_valid_jpeg(client):
    """Fix 2 — scenario 4a: Real JPEG bytes with .jpg extension accepted."""
    resp = _upload(client, "photo.jpg", VALID_JPEG_BYTES, "image/jpeg")
    assert resp.status_code == 201


def test_upload_valid_png(client):
    """Fix 2 — scenario 4b: Real PNG bytes with .png extension accepted."""
    resp = _upload(client, "scan.png", VALID_PNG_BYTES, "image/png")
    assert resp.status_code == 201


def test_upload_valid_webp(client):
    """Fix 2 — scenario 4c: Real WEBP bytes with .webp extension accepted."""
    resp = _upload(client, "shot.webp", VALID_WEBP_BYTES, "image/webp")
    assert resp.status_code == 201


def test_upload_valid_pdf(client):
    """Fix 2 — scenario 4d: Real PDF bytes with .pdf extension accepted."""
    resp = _upload(client, "bill.pdf", VALID_PDF_BYTES, "application/pdf")
    assert resp.status_code == 201


def test_upload_executable_renamed_to_jpg(client):
    """Fix 2 — scenario 5: ELF executable renamed to .jpg is rejected."""
    elf_header = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 108  # 64-bit ELF magic
    resp = _upload(client, "malware.jpg", elf_header, "image/jpeg")
    assert resp.status_code == 400
    # Must NOT accept unrecognised content masquerading as JPEG
    assert "not a recognised" in resp.json()["detail"] or "does not match" in resp.json()["detail"]


def test_upload_text_renamed_to_pdf(client):
    """Fix 2 — scenario 6: Plain text renamed to .pdf is rejected."""
    text_content = b"Hello, I am not a PDF.\n" * 20
    resp = _upload(client, "fake.pdf", text_content, "application/pdf")
    assert resp.status_code == 400
    assert "not a recognised" in resp.json()["detail"] or "does not match" in resp.json()["detail"]


def test_upload_jpeg_renamed_to_pdf(client):
    """Fix 2: JPEG bytes sent with a .pdf extension are rejected (mismatched format)."""
    resp = _upload(client, "image.pdf", VALID_JPEG_BYTES, "application/pdf")
    assert resp.status_code == 400
    assert "does not match" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Original extraction tests (Fix 3 — updated to send AI key header)
# ---------------------------------------------------------------------------

def test_submit_extraction(client):
    """Fix 3: Correct AI key allows extraction to proceed."""
    upload_resp = _upload(client, "receipt.jpg", VALID_JPEG_BYTES, "image/jpeg")
    assert upload_resp.status_code == 201
    receipt_id = upload_resp.json()["id"]

    response = client.post(
        f"/api/receipts/{receipt_id}/extraction",
        json=_extraction_payload(),
        headers=AI_KEY_HEADER,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["merchant_name"] == "Mario's Pizzeria"
    assert data["extraction_status"] == "completed"
    assert len(data["items"]) == 2


def test_submit_extraction_duplicate(client):
    """Duplicate extraction submission is rejected with 409."""
    upload_resp = _upload(client, "receipt.jpg", VALID_JPEG_BYTES, "image/jpeg")
    receipt_id = upload_resp.json()["id"]

    payload = {
        "merchant_name": "Test",
        "currency": "USD",
        "subtotal": "10.00",
        "tax": "1.00",
        "total": "11.00",
        "items": [
            {
                "item_name": "Item 1",
                "quantity": 1,
                "unit_price": "10.00",
                "total_price": "10.00",
            }
        ],
    }
    # First submission
    client.post(f"/api/receipts/{receipt_id}/extraction", json=payload, headers=AI_KEY_HEADER)

    # Duplicate submission should be rejected
    response = client.post(
        f"/api/receipts/{receipt_id}/extraction", json=payload, headers=AI_KEY_HEADER
    )
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Fix 3: AI service key authentication tests
# ---------------------------------------------------------------------------

def test_extraction_missing_ai_key_returns_401(client):
    """Fix 3 — scenario 7: Missing X-Internal-Service-Key header returns 401."""
    upload_resp = _upload(client, "receipt.jpg", VALID_JPEG_BYTES, "image/jpeg")
    receipt_id = upload_resp.json()["id"]

    response = client.post(
        f"/api/receipts/{receipt_id}/extraction",
        json=_extraction_payload(),
        # No headers — intentionally omitted
    )
    assert response.status_code == 401
    assert "X-Internal-Service-Key" in response.json()["detail"]


def test_extraction_incorrect_ai_key_returns_403(client):
    """Fix 3 — scenario 8: Wrong X-Internal-Service-Key header returns 403."""
    upload_resp = _upload(client, "receipt.jpg", VALID_JPEG_BYTES, "image/jpeg")
    receipt_id = upload_resp.json()["id"]

    response = client.post(
        f"/api/receipts/{receipt_id}/extraction",
        json=_extraction_payload(),
        headers={"X-Internal-Service-Key": "totally-wrong-secret"},
    )
    assert response.status_code == 403
    assert "Invalid" in response.json()["detail"]


def test_extraction_correct_ai_key_returns_200(client):
    """Fix 3 — scenario 9: Correct X-Internal-Service-Key header returns 200."""
    upload_resp = _upload(client, "receipt.jpg", VALID_JPEG_BYTES, "image/jpeg")
    receipt_id = upload_resp.json()["id"]

    response = client.post(
        f"/api/receipts/{receipt_id}/extraction",
        json=_extraction_payload(),
        headers=AI_KEY_HEADER,
    )
    assert response.status_code == 200
    assert response.json()["extraction_status"] == "completed"

