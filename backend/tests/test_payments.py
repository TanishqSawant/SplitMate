"""Tests for the PayPal payment lifecycle (order creation, capture, duplicate prevention, status transitions)."""

import io
import uuid

from app.models.models import Payment, PaymentStatus
from tests.conftest import TEST_INTERNAL_SERVICE_SECRET, VALID_JPEG_BYTES

AI_KEY_HEADER = {"X-Internal-Service-Key": TEST_INTERNAL_SERVICE_SECRET}


def _create_payment_setup(client):
    """Helper: create group -> members -> receipt -> expense -> splits -> return payment_id."""
    # Group + member
    group_resp = client.post("/api/groups", json={"name": "Payment Test Group"})
    group_id = group_resp.json()["id"]
    member_resp = client.post(
        f"/api/groups/{group_id}/members",
        json={"name": "Alice", "email": "alice@example.com"},
    )
    member_id = member_resp.json()["id"]

    # Receipt + extraction
    upload_resp = client.post(
        "/api/receipts/upload",
        files={"file": ("r.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")},
    )
    receipt_id = upload_resp.json()["id"]
    client.post(
        f"/api/receipts/{receipt_id}/extraction",
        json={
            "merchant_name": "Test Restaurant",
            "currency": "USD",
            "subtotal": "20.00",
            "tax": "1.60",
            "total": "21.60",
            "items": [
                {
                    "item_name": "Salad",
                    "quantity": 1,
                    "unit_price": "20.00",
                    "total_price": "20.00",
                }
            ],
        },
        headers=AI_KEY_HEADER,
    )

    receipt_data = client.get(f"/api/receipts/{receipt_id}").json()
    item_id = receipt_data["items"][0]["id"]

    # Expense
    expense_resp = client.post(
        "/api/expenses",
        json={
            "group_id": group_id,
            "receipt_id": receipt_id,
            "total_amount": "21.60",
            "currency": "USD",
        },
    )
    expense_id = expense_resp.json()["id"]

    # Assign item
    client.post(
        f"/api/expenses/{expense_id}/assign",
        json={
            "assignments": [
                {
                    "receipt_item_id": item_id,
                    "member_id": member_id,
                    "share_quantity": "1",
                }
            ]
        },
    )

    # Initialize payments
    init_resp = client.post(f"/api/expenses/{expense_id}/initialize-payments")
    assert init_resp.status_code == 201
    payments = init_resp.json()
    assert len(payments) == 1
    return payments[0]["id"], expense_id


def test_get_payment(client):
    payment_id, _ = _create_payment_setup(client)
    response = client.get(f"/api/payments/{payment_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["amount"] == "21.60"
    assert data["currency"] == "USD"


def test_get_payment_not_found(client):
    response = client.get(f"/api/payments/{uuid.uuid4()}")
    assert response.status_code == 404


def test_create_order_success(client):
    """Creating a PayPal order should move status to order_created and set paypal_order_id."""
    payment_id, _ = _create_payment_setup(client)
    response = client.post(f"/api/payments/{payment_id}/create-order", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "order_created"
    assert data["paypal_order_id"] is not None
    assert len(data["paypal_order_id"]) > 0


def test_create_order_conflict_when_already_created(client):
    """Cannot create an order twice for the same payment."""
    payment_id, _ = _create_payment_setup(client)
    first_resp = client.post(f"/api/payments/{payment_id}/create-order", json={})
    assert first_resp.status_code == 200

    second_resp = client.post(f"/api/payments/{payment_id}/create-order", json={})
    assert second_resp.status_code == 409


def test_capture_returns_409_for_pending(client):
    """Cannot capture a payment that is still in pending state (no order created)."""
    payment_id, _ = _create_payment_setup(client)
    response = client.post(
        f"/api/payments/{payment_id}/capture",
        json={"paypal_order_id": "FAKE-ORDER-123"},
    )
    assert response.status_code == 409


def test_capture_success_flow(client):
    """Full PayPal flow: pending -> order_created -> captured."""
    payment_id, _ = _create_payment_setup(client)

    # 1. Create order
    order_resp = client.post(f"/api/payments/{payment_id}/create-order", json={})
    assert order_resp.status_code == 200
    paypal_order_id = order_resp.json()["paypal_order_id"]

    # 2. Capture payment
    capture_resp = client.post(
        f"/api/payments/{payment_id}/capture",
        json={"paypal_order_id": paypal_order_id},
    )
    assert capture_resp.status_code == 200
    data = capture_resp.json()
    assert data["status"] == "captured"
    assert data["paypal_capture_id"] is not None


def test_capture_duplicate_prevented(client):
    """Capturing an already captured payment should return 409."""
    payment_id, _ = _create_payment_setup(client)

    # Create & capture
    order_resp = client.post(f"/api/payments/{payment_id}/create-order", json={})
    paypal_order_id = order_resp.json()["paypal_order_id"]

    client.post(
        f"/api/payments/{payment_id}/capture",
        json={"paypal_order_id": paypal_order_id},
    )

    # Attempt second capture
    dup_resp = client.post(
        f"/api/payments/{payment_id}/capture",
        json={"paypal_order_id": paypal_order_id},
    )
    assert dup_resp.status_code == 409
    assert "already captured" in dup_resp.json()["detail"].lower()


def test_capture_order_id_mismatch(client):
    """Capture fails with 400 if order ID does not match payment record."""
    payment_id, _ = _create_payment_setup(client)
    client.post(f"/api/payments/{payment_id}/create-order", json={})

    mismatch_resp = client.post(
        f"/api/payments/{payment_id}/capture",
        json={"paypal_order_id": "MISMATCHED-ORDER-ID"},
    )
    assert mismatch_resp.status_code == 400


def test_list_expense_payments(client):
    payment_id, expense_id = _create_payment_setup(client)
    resp = client.get(f"/api/payments/expense/{expense_id}")
    assert resp.status_code == 200
    payments = resp.json()
    assert len(payments) == 1
    assert payments[0]["id"] == payment_id
