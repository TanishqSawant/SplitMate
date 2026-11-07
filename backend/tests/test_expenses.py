"""Tests for the expenses API — create, assign, tax distribution, split reconciliation, and payment initialization."""

from decimal import Decimal
import io
import uuid

from app.models.models import Payment, PaymentStatus
from app.db.session import get_db


def _setup_group_with_members(client, member_names: list[str]):
    """Helper: create a group and add members, return (group_id, member_ids)."""
    group_resp = client.post("/api/groups", json={"name": "Test Dinner"})
    group_id = group_resp.json()["id"]

    member_ids = []
    for name in member_names:
        resp = client.post(
            f"/api/groups/{group_id}/members",
            json={"name": name, "email": f"{name.lower()}@example.com"},
        )
        member_ids.append(resp.json()["id"])

    return group_id, member_ids


def _upload_and_extract(client, subtotal="40.00", tax="3.20", total="43.20"):
    """Helper: upload a receipt and submit extraction, return receipt with items."""
    upload_resp = client.post(
        "/api/receipts/upload",
        files={"file": ("receipt.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    )
    receipt_id = upload_resp.json()["id"]

    extraction = {
        "merchant_name": "Test Restaurant",
        "currency": "USD",
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "items": [
            {
                "item_name": "Burger",
                "quantity": 1,
                "unit_price": "15.00",
                "total_price": "15.00",
            },
            {
                "item_name": "Pizza",
                "quantity": 1,
                "unit_price": "25.00",
                "total_price": "25.00",
            },
        ],
    }
    extract_resp = client.post(
        f"/api/receipts/{receipt_id}/extraction", json=extraction
    )
    return extract_resp.json()


def test_create_expense(client):
    group_id, _ = _setup_group_with_members(client, ["Alice"])
    receipt = _upload_and_extract(client)

    response = client.post(
        "/api/expenses",
        json={
            "group_id": group_id,
            "receipt_id": receipt["id"],
            "total_amount": "43.20",
            "currency": "USD",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["group_id"] == group_id
    assert data["receipt_id"] == receipt["id"]


def test_create_expense_group_not_found(client):
    response = client.post(
        "/api/expenses",
        json={
            "group_id": str(uuid.uuid4()),
            "total_amount": "10.00",
            "currency": "USD",
        },
    )
    assert response.status_code == 404


def test_assign_and_split_with_tax(client):
    """Full flow: create group, upload receipt, create expense, assign, calculate split with tax."""
    group_id, member_ids = _setup_group_with_members(client, ["Alice", "Bob"])
    receipt = _upload_and_extract(client, subtotal="40.00", tax="3.20", total="43.20")
    items = receipt["items"]

    # Create expense
    expense_resp = client.post(
        "/api/expenses",
        json={
            "group_id": group_id,
            "receipt_id": receipt["id"],
            "total_amount": "43.20",
            "currency": "USD",
        },
    )
    expense_id = expense_resp.json()["id"]

    # Assign: Alice gets the Burger ($15), Bob gets the Pizza ($25)
    assign_resp = client.post(
        f"/api/expenses/{expense_id}/assign",
        json={
            "assignments": [
                {
                    "receipt_item_id": items[0]["id"],
                    "member_id": member_ids[0],
                    "share_quantity": "1",
                },
                {
                    "receipt_item_id": items[1]["id"],
                    "member_id": member_ids[1],
                    "share_quantity": "1",
                },
            ]
        },
    )
    assert assign_resp.status_code == 201

    # Get splits (Read-only)
    splits_resp = client.get(f"/api/expenses/{expense_id}/splits")
    assert splits_resp.status_code == 200
    splits_data = splits_resp.json()
    assert len(splits_data["splits"]) == 2

    splits_by_name = {s["member_name"]: s for s in splits_data["splits"]}

    # Alice: $15 item + $1.20 tax (15/40 of $3.20) = $16.20
    assert float(splits_by_name["Alice"]["allocated_subtotal"]) == 15.00
    assert float(splits_by_name["Alice"]["allocated_tax"]) == 1.20
    assert float(splits_by_name["Alice"]["amount"]) == 16.20

    # Bob: $25 item + $2.00 tax (25/40 of $3.20) = $27.00
    assert float(splits_by_name["Bob"]["allocated_subtotal"]) == 25.00
    assert float(splits_by_name["Bob"]["allocated_tax"]) == 2.00
    assert float(splits_by_name["Bob"]["amount"]) == 27.00

    # Reconciled total matches expense.total_amount
    total_split = sum(Decimal(str(s["amount"])) for s in splits_data["splits"])
    assert total_split == Decimal("43.20")


def test_split_item_between_members(client):
    """Two members share a single pizza equally."""
    group_id, member_ids = _setup_group_with_members(client, ["Alice", "Bob"])
    receipt = _upload_and_extract(client, subtotal="25.00", tax="0.00", total="25.00")
    pizza_item = receipt["items"][1]  # Pizza at $25.00

    expense_resp = client.post(
        "/api/expenses",
        json={
            "group_id": group_id,
            "receipt_id": receipt["id"],
            "total_amount": "25.00",
            "currency": "USD",
        },
    )
    expense_id = expense_resp.json()["id"]

    # Both share the pizza equally (share_quantity = 0.5 each)
    client.post(
        f"/api/expenses/{expense_id}/assign",
        json={
            "assignments": [
                {
                    "receipt_item_id": pizza_item["id"],
                    "member_id": member_ids[0],
                    "share_quantity": "0.5",
                },
                {
                    "receipt_item_id": pizza_item["id"],
                    "member_id": member_ids[1],
                    "share_quantity": "0.5",
                },
            ]
        },
    )

    splits_resp = client.get(f"/api/expenses/{expense_id}/splits")
    splits = splits_resp.json()["splits"]
    assert len(splits) == 2
    for split in splits:
        assert float(split["amount"]) == 12.50


def test_splits_endpoint_is_read_only(client):
    """GET /api/expenses/{id}/splits must NOT create any payment records."""
    group_id, member_ids = _setup_group_with_members(client, ["Alice"])
    receipt = _upload_and_extract(client)
    expense_resp = client.post(
        "/api/expenses",
        json={
            "group_id": group_id,
            "receipt_id": receipt["id"],
            "total_amount": "15.00",
            "currency": "USD",
        },
    )
    expense_id = expense_resp.json()["id"]

    client.post(
        f"/api/expenses/{expense_id}/assign",
        json={
            "assignments": [
                {
                    "receipt_item_id": receipt["items"][0]["id"],
                    "member_id": member_ids[0],
                    "share_quantity": "1",
                }
            ]
        },
    )

    # Call GET splits multiple times
    client.get(f"/api/expenses/{expense_id}/splits")
    client.get(f"/api/expenses/{expense_id}/splits")

    # Verify no Payment record was inserted into database
    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    payment_count = db.query(Payment).filter(Payment.expense_id == expense_id).count()
    assert payment_count == 0


def test_initialize_payments_success(client):
    """POST /api/expenses/{id}/initialize-payments creates pending payments."""
    group_id, member_ids = _setup_group_with_members(client, ["Alice", "Bob"])
    receipt = _upload_and_extract(client, subtotal="40.00", tax="3.20", total="43.20")
    items = receipt["items"]

    expense_resp = client.post(
        "/api/expenses",
        json={
            "group_id": group_id,
            "receipt_id": receipt["id"],
            "total_amount": "43.20",
            "currency": "USD",
        },
    )
    expense_id = expense_resp.json()["id"]

    client.post(
        f"/api/expenses/{expense_id}/assign",
        json={
            "assignments": [
                {
                    "receipt_item_id": items[0]["id"],
                    "member_id": member_ids[0],
                    "share_quantity": "1",
                },
                {
                    "receipt_item_id": items[1]["id"],
                    "member_id": member_ids[1],
                    "share_quantity": "1",
                },
            ]
        },
    )

    # Initialize payments
    init_resp = client.post(f"/api/expenses/{expense_id}/initialize-payments")
    assert init_resp.status_code == 201
    payments = init_resp.json()
    assert len(payments) == 2
    for p in payments:
        assert p["status"] == "pending"
        assert p["expense_id"] == expense_id

    # Re-initialization updates existing pending records cleanly
    re_init_resp = client.post(f"/api/expenses/{expense_id}/initialize-payments")
    assert re_init_resp.status_code == 201
    assert len(re_init_resp.json()) == 2


def test_initialize_payments_conflict_when_captured(client):
    """Cannot re-initialize payments if any payment is order_created or captured."""
    group_id, member_ids = _setup_group_with_members(client, ["Alice"])
    receipt = _upload_and_extract(client)
    expense_resp = client.post(
        "/api/expenses",
        json={
            "group_id": group_id,
            "receipt_id": receipt["id"],
            "total_amount": "15.00",
            "currency": "USD",
        },
    )
    expense_id = expense_resp.json()["id"]
    client.post(
        f"/api/expenses/{expense_id}/assign",
        json={
            "assignments": [
                {
                    "receipt_item_id": receipt["items"][0]["id"],
                    "member_id": member_ids[0],
                    "share_quantity": "1",
                }
            ]
        },
    )

    client.post(f"/api/expenses/{expense_id}/initialize-payments")

    # Manually transition payment to CAPTURED
    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    payment = db.query(Payment).filter(Payment.expense_id == expense_id).first()
    payment.status = PaymentStatus.CAPTURED
    db.commit()

    # Re-initialize should be rejected with 409 Conflict
    response = client.post(f"/api/expenses/{expense_id}/initialize-payments")
    assert response.status_code == 409
    assert "already in state 'captured'" in response.json()["detail"]


def test_cross_group_assignment_rejected(client):
    """Cannot assign an expense to a member of a different group."""
    group1_id, member1_ids = _setup_group_with_members(client, ["MemberGroup1"])
    group2_id, member2_ids = _setup_group_with_members(client, ["MemberGroup2"])
    receipt = _upload_and_extract(client)

    expense_resp = client.post(
        "/api/expenses",
        json={
            "group_id": group1_id,
            "receipt_id": receipt["id"],
            "total_amount": "15.00",
            "currency": "USD",
        },
    )
    expense_id = expense_resp.json()["id"]

    # Attempt to assign MemberGroup2 to Group1's expense
    resp = client.post(
        f"/api/expenses/{expense_id}/assign",
        json={
            "assignments": [
                {
                    "receipt_item_id": receipt["items"][0]["id"],
                    "member_id": member2_ids[0],
                    "share_quantity": "1",
                }
            ]
        },
    )
    assert resp.status_code == 400
    assert "not part of this expense's group" in resp.json()["detail"]


def test_cross_receipt_item_assignment_rejected(client):
    """Cannot assign a receipt item that belongs to a different receipt."""
    group_id, member_ids = _setup_group_with_members(client, ["Alice"])
    receipt1 = _upload_and_extract(client)
    receipt2 = _upload_and_extract(client)

    expense_resp = client.post(
        "/api/expenses",
        json={
            "group_id": group_id,
            "receipt_id": receipt1["id"],
            "total_amount": "15.00",
            "currency": "USD",
        },
    )
    expense_id = expense_resp.json()["id"]

    # Attempt to assign an item from receipt2 to an expense linked to receipt1
    resp = client.post(
        f"/api/expenses/{expense_id}/assign",
        json={
            "assignments": [
                {
                    "receipt_item_id": receipt2["items"][0]["id"],
                    "member_id": member_ids[0],
                    "share_quantity": "1",
                }
            ]
        },
    )
    assert resp.status_code == 400
    assert "does not belong to the receipt associated with this expense" in resp.json()["detail"]


def test_over_assignment_rejected(client):
    """Assigning more than the item's purchased quantity is rejected."""
    group_id, member_ids = _setup_group_with_members(client, ["Alice", "Bob"])
    receipt = _upload_and_extract(client)
    burger_item = receipt["items"][0]  # quantity = 1

    expense_resp = client.post(
        "/api/expenses",
        json={
            "group_id": group_id,
            "receipt_id": receipt["id"],
            "total_amount": "15.00",
            "currency": "USD",
        },
    )
    expense_id = expense_resp.json()["id"]

    # Alice takes 1, Bob takes 1 -> Total 2 > 1
    resp = client.post(
        f"/api/expenses/{expense_id}/assign",
        json={
            "assignments": [
                {
                    "receipt_item_id": burger_item["id"],
                    "member_id": member_ids[0],
                    "share_quantity": "1",
                },
                {
                    "receipt_item_id": burger_item["id"],
                    "member_id": member_ids[1],
                    "share_quantity": "1",
                },
            ]
        },
    )
    assert resp.status_code == 400
    assert "exceeds purchased quantity" in resp.json()["detail"]


def test_penny_rounding_reconciliation(client):
    """3 members splitting an odd amount ($10.00) reconcile to exactly $10.00 down to the penny."""
    group_id, member_ids = _setup_group_with_members(client, ["Alice", "Bob", "Charlie"])

    # Upload receipt with $10 total
    upload_resp = client.post(
        "/api/receipts/upload",
        files={"file": ("r.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    )
    receipt_id = upload_resp.json()["id"]
    client.post(
        f"/api/receipts/{receipt_id}/extraction",
        json={
            "merchant_name": "Penny Cafe",
            "currency": "USD",
            "subtotal": "10.00",
            "tax": "0.00",
            "total": "10.00",
            "items": [
                {
                    "item_name": "Combo Meal",
                    "quantity": 3,
                    "unit_price": "3.33",
                    "total_price": "10.00",
                }
            ],
        },
    )
    item_id = client.get(f"/api/receipts/{receipt_id}").json()["items"][0]["id"]

    expense_resp = client.post(
        "/api/expenses",
        json={
            "group_id": group_id,
            "receipt_id": receipt_id,
            "total_amount": "10.00",
            "currency": "USD",
        },
    )
    expense_id = expense_resp.json()["id"]

    # Each takes 1 share out of 3
    client.post(
        f"/api/expenses/{expense_id}/assign",
        json={
            "assignments": [
                {
                    "receipt_item_id": item_id,
                    "member_id": member_ids[0],
                    "share_quantity": "1",
                },
                {
                    "receipt_item_id": item_id,
                    "member_id": member_ids[1],
                    "share_quantity": "1",
                },
                {
                    "receipt_item_id": item_id,
                    "member_id": member_ids[2],
                    "share_quantity": "1",
                },
            ]
        },
    )

    splits_resp = client.get(f"/api/expenses/{expense_id}/splits")
    assert splits_resp.status_code == 200
    splits = splits_resp.json()["splits"]

    # Sum of splits must be exactly 10.00
    amounts = [Decimal(str(s["amount"])) for s in splits]
    assert sum(amounts) == Decimal("10.00")
    # One gets 3.34, two get 3.33
    assert sorted([float(a) for a in amounts]) == [3.33, 3.33, 3.34]
