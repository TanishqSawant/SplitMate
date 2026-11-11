"""Tests for authorization and IDOR protection across groups, receipts, expenses, and payments."""

import io
from tests.conftest import (
    TEST_INTERNAL_SERVICE_SECRET,
    VALID_JPEG_BYTES,
    create_user_and_client,
)

AI_KEY_HEADER = {"X-Internal-Service-Key": TEST_INTERNAL_SERVICE_SECRET}


def _upload_and_extract_for_client(c, total="30.00", subtotal="30.00", tax="0.00"):
    """Helper: upload a receipt and submit AI extraction as client 'c'."""
    upload_resp = c.post(
        "/api/receipts/upload",
        files={"file": ("receipt.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    receipt_id = upload_resp.json()["id"]

    extract_resp = c.post(
        f"/api/receipts/{receipt_id}/extraction",
        json={
            "merchant_name": "Test Bistro",
            "currency": "USD",
            "subtotal": subtotal,
            "tax": tax,
            "total": total,
            "items": [
                {
                    "item_name": "Pasta",
                    "quantity": 1,
                    "unit_price": subtotal,
                    "total_price": subtotal,
                }
            ],
        },
        headers=AI_KEY_HEADER,
    )
    assert extract_resp.status_code == 200
    return extract_resp.json()


def test_user_a_cannot_access_user_b_private_group(db_session, client):
    """User A cannot read or list User B's private group (returns 404 to avoid leaking existence)."""
    user_b, client_b, _ = create_user_and_client(
        db_session, email="user_b@example.com", name="User B"
    )

    # User B creates a private group
    grp_b = client_b.post("/api/groups", json={"name": "User B Secret Group"}).json()
    group_b_id = grp_b["id"]

    # User A (client) tries to access User B's group
    resp = client.get(f"/api/groups/{group_b_id}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Group not found."

    # User A listing their groups does not include User B's group
    list_resp = client.get("/api/groups")
    assert list_resp.status_code == 200
    group_ids = [g["id"] for g in list_resp.json()]
    assert group_b_id not in group_ids


def test_user_a_cannot_add_members_to_user_b_group(db_session, client):
    """User A cannot add members to User B's group."""
    user_b, client_b, _ = create_user_and_client(
        db_session, email="user_b2@example.com", name="User B"
    )
    grp_b = client_b.post("/api/groups", json={"name": "User B Group"}).json()

    resp = client.post(
        f"/api/groups/{grp_b['id']}/members",
        json={"name": "Intruder", "email": "intruder@example.com"},
    )
    assert resp.status_code == 404


def test_user_a_cannot_access_user_b_receipt(db_session, client):
    """User A cannot access a receipt uploaded by User B that is not linked to any shared group."""
    user_b, client_b, _ = create_user_and_client(
        db_session, email="user_b_receipt@example.com", name="User B"
    )
    receipt_b = _upload_and_extract_for_client(client_b)

    # User A tries to get User B's receipt
    resp = client.get(f"/api/receipts/{receipt_b['id']}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Receipt not found."


def test_user_a_cannot_create_expense_with_user_b_receipt(db_session, client):
    """User A cannot use User B's receipt in their own group (cross-tenant receipt theft)."""
    user_b, client_b, _ = create_user_and_client(
        db_session, email="user_b_theft@example.com", name="User B"
    )
    receipt_b = _upload_and_extract_for_client(client_b, total="50.00", subtotal="50.00")

    # User A creates their own group
    grp_a = client.post("/api/groups", json={"name": "User A Group"}).json()

    # User A tries to create an expense linking User B's receipt
    resp = client.post(
        "/api/expenses",
        json={
            "group_id": grp_a["id"],
            "receipt_id": receipt_b["id"],
            "total_amount": "50.00",
            "currency": "USD",
        },
    )
    assert resp.status_code == 404
    assert "Receipt not found" in resp.json()["detail"]


def test_user_a_cannot_modify_user_b_expense_assignments(db_session, client):
    """User A cannot create or alter assignments for an expense in User B's group."""
    user_b, client_b, _ = create_user_and_client(
        db_session, email="user_b_exp@example.com", name="User B"
    )
    receipt_b = _upload_and_extract_for_client(client_b, total="25.00", subtotal="25.00")
    grp_b = client_b.post("/api/groups", json={"name": "User B Expenses"}).json()
    exp_b = client_b.post(
        "/api/expenses",
        json={
            "group_id": grp_b["id"],
            "receipt_id": receipt_b["id"],
            "total_amount": "25.00",
            "currency": "USD",
        },
    ).json()

    # User A attempts to assign items in User B's expense
    resp = client.post(
        f"/api/expenses/{exp_b['id']}/assign",
        json={
            "assignments": [
                {
                    "receipt_item_id": receipt_b["items"][0]["id"],
                    "member_id": grp_b["id"],
                    "share_quantity": "1",
                }
            ]
        },
    )
    assert resp.status_code == 404


def test_user_a_cannot_initialize_payments_for_user_b_group(db_session, client):
    """User A cannot trigger payment initialization for an unrelated group's expense."""
    user_b, client_b, _ = create_user_and_client(
        db_session, email="user_b_init@example.com", name="User B"
    )
    receipt_b = _upload_and_extract_for_client(client_b, total="20.00", subtotal="20.00")
    grp_b = client_b.post("/api/groups", json={"name": "User B Bill"}).json()
    exp_b = client_b.post(
        "/api/expenses",
        json={
            "group_id": grp_b["id"],
            "receipt_id": receipt_b["id"],
            "total_amount": "20.00",
            "currency": "USD",
        },
    ).json()

    resp = client.post(f"/api/expenses/{exp_b['id']}/initialize-payments")
    assert resp.status_code == 404


def test_user_a_cannot_access_user_b_payment_record(db_session, client):
    """User A cannot view User B's private payment record."""
    user_b, client_b, _ = create_user_and_client(
        db_session, email="user_b_pay@example.com", name="User B"
    )
    receipt_b = _upload_and_extract_for_client(client_b, total="15.00", subtotal="15.00")
    grp_b = client_b.post("/api/groups", json={"name": "Payment Group"}).json()
    mem_b = client_b.post(
        f"/api/groups/{grp_b['id']}/members",
        json={"name": "Member B", "email": "member_b@example.com"},
    ).json()

    exp_b = client_b.post(
        "/api/expenses",
        json={
            "group_id": grp_b["id"],
            "receipt_id": receipt_b["id"],
            "total_amount": "15.00",
            "currency": "USD",
        },
    ).json()

    client_b.post(
        f"/api/expenses/{exp_b['id']}/assign",
        json={
            "assignments": [
                {
                    "receipt_item_id": receipt_b["items"][0]["id"],
                    "member_id": mem_b["id"],
                    "share_quantity": "1",
                }
            ]
        },
    )

    init_resp = client_b.post(f"/api/expenses/{exp_b['id']}/initialize-payments")
    assert init_resp.status_code == 201
    payment_b_id = init_resp.json()[0]["id"]

    # User A tries to read User B's payment
    resp = client.get(f"/api/payments/{payment_b_id}")
    assert resp.status_code == 404


def test_user_cannot_pay_another_members_share(db_session):
    """A member of the group cannot create an order or capture a payment belonging to someone else."""
    user_alice, client_alice, _ = create_user_and_client(
        db_session, email="alice_pay@example.com", name="Alice"
    )
    user_bob, client_bob, _ = create_user_and_client(
        db_session, email="bob_pay@example.com", name="Bob"
    )

    # Alice creates group and adds Bob
    grp = client_alice.post("/api/groups", json={"name": "Alice & Bob Dinner"}).json()
    mem_alice = client_alice.post(
        f"/api/groups/{grp['id']}/members",
        json={"name": "Alice", "email": "alice_pay@example.com"},
    ).json()
    mem_bob = client_alice.post(
        f"/api/groups/{grp['id']}/members",
        json={"name": "Bob", "email": "bob_pay@example.com"},
    ).json()

    # Upload receipt with 2 items
    upload_resp = client_alice.post(
        "/api/receipts/upload",
        files={"file": ("r.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")},
    )
    r_id = upload_resp.json()["id"]
    client_alice.post(
        f"/api/receipts/{r_id}/extraction",
        json={
            "merchant_name": "Duo Diner",
            "currency": "USD",
            "subtotal": "30.00",
            "tax": "0.00",
            "total": "30.00",
            "items": [
                {"item_name": "Item 1", "quantity": 1, "unit_price": "15.00", "total_price": "15.00"},
                {"item_name": "Item 2", "quantity": 1, "unit_price": "15.00", "total_price": "15.00"},
            ],
        },
        headers=AI_KEY_HEADER,
    )
    r_items = client_alice.get(f"/api/receipts/{r_id}").json()["items"]

    exp = client_alice.post(
        "/api/expenses",
        json={
            "group_id": grp["id"],
            "receipt_id": r_id,
            "total_amount": "30.00",
            "currency": "USD",
        },
    ).json()

    # Assign Item 1 to Alice, Item 2 to Bob
    client_alice.post(
        f"/api/expenses/{exp['id']}/assign",
        json={
            "assignments": [
                {"receipt_item_id": r_items[0]["id"], "member_id": mem_alice["id"], "share_quantity": "1"},
                {"receipt_item_id": r_items[1]["id"], "member_id": mem_bob["id"], "share_quantity": "1"},
            ]
        },
    )

    init_payments = client_alice.post(f"/api/expenses/{exp['id']}/initialize-payments").json()
    bob_payment = next(p for p in init_payments if p["member_id"] == mem_bob["id"])

    # Alice tries to create PayPal order for Bob's payment share -> 403 Forbidden!
    resp = client_alice.post(
        f"/api/payments/{bob_payment['id']}/create-order",
        json={},
    )
    assert resp.status_code == 403
    assert "only manage or pay your own share" in resp.json()["detail"].lower()

    # Bob CAN initiate his own order (passes auth check; returns 200 with mock, or 501/502 without live PayPal creds)
    bob_resp = client_bob.post(
        f"/api/payments/{bob_payment['id']}/create-order",
        json={},
    )
    assert bob_resp.status_code in (200, 501, 502)
    assert bob_resp.status_code != 403


def test_legitimate_group_member_can_access_shared_resources(db_session):
    """When User B is added as a member of User A's group, User B can access the shared group & receipt."""
    user_a, client_a, _ = create_user_and_client(
        db_session, email="owner_a@example.com", name="Owner A"
    )
    user_b, client_b, _ = create_user_and_client(
        db_session, email="member_b_legit@example.com", name="Member B"
    )

    # User A creates group and adds User B
    grp = client_a.post("/api/groups", json={"name": "Shared Trip"}).json()
    client_a.post(
        f"/api/groups/{grp['id']}/members",
        json={"name": "Member B", "email": "member_b_legit@example.com"},
    )

    # User A uploads receipt and creates expense
    receipt = _upload_and_extract_for_client(client_a, total="40.00", subtotal="40.00")
    exp = client_a.post(
        "/api/expenses",
        json={
            "group_id": grp["id"],
            "receipt_id": receipt["id"],
            "total_amount": "40.00",
            "currency": "USD",
        },
    ).json()

    # User B can view the group
    grp_resp = client_b.get(f"/api/groups/{grp['id']}")
    assert grp_resp.status_code == 200
    assert grp_resp.json()["name"] == "Shared Trip"

    # User B can view the group's expense
    exp_resp = client_b.get(f"/api/expenses/{exp['id']}")
    assert exp_resp.status_code == 200

    # User B can view the receipt linked to the shared group expense
    rcpt_resp = client_b.get(f"/api/receipts/{receipt['id']}")
    assert rcpt_resp.status_code == 200

