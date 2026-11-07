"""Tests for the receipts API."""

import io


def test_upload_receipt(client):
    file_content = b"fake image content"
    response = client.post(
        "/api/receipts/upload",
        files={"file": ("receipt.jpg", io.BytesIO(file_content), "image/jpeg")},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["original_filename"] == "receipt.jpg"
    assert data["extraction_status"] == "pending"
    assert "id" in data


def test_upload_receipt_invalid_type(client):
    file_content = b"not a valid file"
    response = client.post(
        "/api/receipts/upload",
        files={"file": ("receipt.txt", io.BytesIO(file_content), "text/plain")},
    )
    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]


def test_get_receipt(client):
    # Upload
    file_content = b"fake image content"
    upload_resp = client.post(
        "/api/receipts/upload",
        files={"file": ("receipt.png", io.BytesIO(file_content), "image/png")},
    )
    receipt_id = upload_resp.json()["id"]

    # Retrieve
    response = client.get(f"/api/receipts/{receipt_id}")
    assert response.status_code == 200
    assert response.json()["original_filename"] == "receipt.png"


def test_get_receipt_not_found(client):
    response = client.get("/api/receipts/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_submit_extraction(client):
    # Upload
    file_content = b"fake image content"
    upload_resp = client.post(
        "/api/receipts/upload",
        files={"file": ("receipt.jpg", io.BytesIO(file_content), "image/jpeg")},
    )
    receipt_id = upload_resp.json()["id"]

    # Submit extraction
    extraction_data = {
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
    response = client.post(
        f"/api/receipts/{receipt_id}/extraction", json=extraction_data
    )
    assert response.status_code == 200
    data = response.json()
    assert data["merchant_name"] == "Mario's Pizzeria"
    assert data["extraction_status"] == "completed"
    assert len(data["items"]) == 2


def test_submit_extraction_duplicate(client):
    # Upload
    file_content = b"fake image content"
    upload_resp = client.post(
        "/api/receipts/upload",
        files={"file": ("receipt.jpg", io.BytesIO(file_content), "image/jpeg")},
    )
    receipt_id = upload_resp.json()["id"]

    extraction_data = {
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
    client.post(f"/api/receipts/{receipt_id}/extraction", json=extraction_data)

    # Duplicate submission should be rejected
    response = client.post(
        f"/api/receipts/{receipt_id}/extraction", json=extraction_data
    )
    assert response.status_code == 409

