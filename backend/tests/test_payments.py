"""Tests for the payments API (interface validation only — PayPal is not integrated)."""


import io


def _create_payment_setup(client):
    """Helper: create group → members → receipt → expense → splits → return payment."""
    # Group + member
    group_resp = client.post("/api/groups", json={"name": "Payment Test"})
    group_id = group_resp.json()["id"]
    member_resp = client.post(
        f"/api/groups/{group_id}/members",
        json={"name": "Alice", "email": "alice@example.com"},
    )
    member_id = member_resp.json()["id"]

    # Receipt + extraction
    upload_resp = client.post(
        "/api/receipts/upload",
        files={"file": ("r.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    )
    receipt_id = upload_resp.json()["id"]
    client.post(
        f"/api/receipts/{receipt_id}/extraction",
        json={
            "merchant_name": "Test",
            "currency": "USD",
            "subtotal": "10.00",
            "tax": "0.80",
            "total": "10.80",
            "items": [
                {
                    "item_name": "Salad",
                    "quantity": 1,
                    "unit_price": "10.00",
                    "total_price": "10.00",
                }
            ],
        },
    )
    receipt_data = client.get(f"/api/receipts/{receipt_id}").json()
    item_id = receipt_data["items"][0]["id"]

    # Expense
    expense_resp = client.post(
        "/api/expenses",
        json={
            "group_id": group_id,
            "receipt_id": receipt_id,
            "total_amount": "10.80",
            "currency": "USD",
        },
    )
    expense_id = expense_resp.json()["id"]

    # Assign and calculate split
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
    splits_resp = client.get(f"/api/expenses/{expense_id}/splits")
    assert splits_resp.status_code == 200

    # Initialize payment via the dedicated POST endpoint
    init_resp = client.post(f"/api/expenses/{expense_id}/initialize-payments")
    assert init_resp.status_code == 201

    # Find the payment that was created
    from app.models.models import Payment
    from app.db.session import get_db

    # Use the overridden db to query
    # Since we can't easily get the payment ID from splits, query via expense
    from sqlalchemy import select

    # Get db session from the dependency override
    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    payment = db.query(Payment).filter(Payment.expense_id == expense_id).first()
    return payment.id


def test_get_payment(client):
    payment_id = _create_payment_setup(client)
    response = client.get(f"/api/payments/{payment_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"


def test_get_payment_not_found(client):
    response = client.get("/api/payments/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_create_order_returns_501(client):
    """PayPal integration is not implemented — should return 501."""
    payment_id = _create_payment_setup(client)
    response = client.post(f"/api/payments/{payment_id}/create-order", json={})
    assert response.status_code == 501


def test_capture_returns_409_for_pending(client):
    """Cannot capture a payment that has not had an order created."""
    payment_id = _create_payment_setup(client)
    response = client.post(
        f"/api/payments/{payment_id}/capture",
        json={"paypal_order_id": "FAKE-ORDER-123"},
    )
    # Should fail because status is 'pending', not 'order_created'
    assert response.status_code == 409

