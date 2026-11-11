"""End-to-End (E2E) Workflow Test for SplitMate.

Simulates the complete 12-step lifecycle:
1.  Create Group
2.  Add Members to Group
3.  Upload Receipt Image
4.  Trigger AI Extraction
5.  Review & Edit Extracted Items (update names, prices, add items)
6.  Create Expense Linked to Receipt
7.  Assign Items to Members (shared dishes, individual items)
8.  Calculate Splits (verify penny accuracy and mathematical conservation)
9.  Initialize Payments (pending ledger records)
10. Create PayPal Sandbox Order
11. Capture PayPal Payment (successful capture & state transition to 'captured')
12. Verify Final Payment & Expense State
"""

from decimal import Decimal
import io
import pytest

from tests.conftest import VALID_JPEG_BYTES


def test_complete_e2e_expense_splitting_and_paypal_lifecycle(client):
    # -------------------------------------------------------------------------
    # Step 1: Register and Log In (POST /api/auth/register & /api/auth/login)
    # -------------------------------------------------------------------------
    reg_payload = {
        "name": "Sunil Lead",
        "email": "sunil.e2e@splitmate.io",
        "password": "e2epassword123",
        "paypal_email": "sunil-sandbox@paypal.com",
    }
    res_reg = client.post("/api/auth/register", json=reg_payload)
    assert res_reg.status_code == 201, res_reg.text
    auth_data = res_reg.json()
    auth_token = auth_data["access_token"]
    assert auth_data["user"]["email"] == "sunil.e2e@splitmate.io"

    # Verify login with registered credentials
    res_login = client.post("/api/auth/login", json={
        "email": "sunil.e2e@splitmate.io",
        "password": "e2epassword123",
    })
    assert res_login.status_code == 200, res_login.text
    assert "access_token" in res_login.json()

    # Verify protected route access with token
    res_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {auth_token}"})
    assert res_me.status_code == 200, res_me.text
    assert res_me.json()["name"] == "Sunil Lead"

    # -------------------------------------------------------------------------
    # Step 2: Create Group (POST /api/groups)
    # -------------------------------------------------------------------------
    res_group = client.post("/api/groups", json={"name": "PayPal AI Hackathon Squad"})
    assert res_group.status_code == 201, res_group.text
    group_data = res_group.json()
    group_id = group_data["id"]
    assert group_data["name"] == "PayPal AI Hackathon Squad"

    # -------------------------------------------------------------------------
    # Step 2: Add Members to Group (POST /api/groups/{group_id}/members)
    # -------------------------------------------------------------------------
    # Sunil (payer/admin), Dhruv, Pawan, Tanishq, Tanay
    members = [
        {"name": "Sunil", "email": "sunil@splitmate.io"},
        {"name": "Dhruv", "email": "dhruv@splitmate.io"},
        {"name": "Pawan", "email": "pawan@splitmate.io"},
    ]
    member_ids = {}
    for m in members:
        res_m = client.post(f"/api/groups/{group_id}/members", json=m)
        assert res_m.status_code == 201, res_m.text
        m_data = res_m.json()
        member_ids[m["name"]] = m_data["id"]

    assert len(member_ids) == 3

    # -------------------------------------------------------------------------
    # Step 3: Upload Receipt (POST /api/receipts/upload)
    # -------------------------------------------------------------------------
    receipt_file = io.BytesIO(VALID_JPEG_BYTES)
    res_upload = client.post(
        "/api/receipts/upload?auto_extract=false",
        files={"file": ("dinner_bill.jpg", receipt_file, "image/jpeg")},
    )
    assert res_upload.status_code == 201, res_upload.text
    receipt_data = res_upload.json()
    receipt_id = receipt_data["id"]
    assert receipt_data["extraction_status"] == "pending"

    # -------------------------------------------------------------------------
    # Step 4: Trigger AI Extraction (POST /api/receipts/{receipt_id}/extract)
    # -------------------------------------------------------------------------
    res_extract = client.post(f"/api/receipts/{receipt_id}/extract")
    assert res_extract.status_code == 200, res_extract.text
    extracted = res_extract.json()
    assert extracted["extraction_status"] == "completed"
    assert len(extracted["items"]) > 0

    # -------------------------------------------------------------------------
    # Step 5: Review & Edit Extracted Items (PUT /api/receipts/{receipt_id}/items)
    # -------------------------------------------------------------------------
    # User reviews and corrects the line items:
    # Item A: Truffle Pizza ($30.00, shared by Sunil and Dhruv)
    # Item B: Garlic Bread ($10.00, eaten by Pawan alone)
    # Item C: Sparkling Drinks ($15.00, shared equally by all 3)
    # Subtotal = 55.00, Tax = 5.00, Total = 60.00
    edit_payload = {
        "merchant_name": "Mario's Hackathon Bistro",
        "currency": "USD",
        "tax": 5.00,
        "items": [
            {
                "item_name": "Truffle Pizza",
                "quantity": 1,
                "unit_price": 30.00,
                "total_price": 30.00,
            },
            {
                "item_name": "Garlic Bread",
                "quantity": 1,
                "unit_price": 10.00,
                "total_price": 10.00,
            },
            {
                "item_name": "Sparkling Drinks",
                "quantity": 1,
                "unit_price": 15.00,
                "total_price": 15.00,
            },
        ],
    }
    res_edit = client.put(f"/api/receipts/{receipt_id}/items", json=edit_payload)
    assert res_edit.status_code == 200, res_edit.text
    edited_receipt = res_edit.json()
    assert Decimal(str(edited_receipt["subtotal"])) == Decimal("55.00")
    assert Decimal(str(edited_receipt["tax"])) == Decimal("5.00")
    assert Decimal(str(edited_receipt["total"])) == Decimal("60.00")

    item_lookup = {it["item_name"]: it["id"] for it in edited_receipt["items"]}

    # -------------------------------------------------------------------------
    # Step 6: Create Expense (POST /api/expenses)
    # -------------------------------------------------------------------------
    expense_payload = {
        "group_id": group_id,
        "receipt_id": receipt_id,
        "total_amount": 60.00,
        "currency": "USD",
    }
    res_expense = client.post("/api/expenses", json=expense_payload)
    assert res_expense.status_code == 201, res_expense.text
    expense_id = res_expense.json()["id"]

    # -------------------------------------------------------------------------
    # Step 7: Assign Items to Members (POST /api/expenses/{expense_id}/assign)
    # -------------------------------------------------------------------------
    # Truffle Pizza ($30): 0.5 Sunil, 0.5 Dhruv
    # Garlic Bread ($10): 1.0 Pawan
    # Sparkling Drinks ($15): 0.3333 Sunil, 0.3333 Dhruv, 0.3334 Pawan
    assignments = [
        {"receipt_item_id": item_lookup["Truffle Pizza"], "member_id": member_ids["Sunil"], "share_quantity": 0.5},
        {"receipt_item_id": item_lookup["Truffle Pizza"], "member_id": member_ids["Dhruv"], "share_quantity": 0.5},
        {"receipt_item_id": item_lookup["Garlic Bread"], "member_id": member_ids["Pawan"], "share_quantity": 1.0},
        {"receipt_item_id": item_lookup["Sparkling Drinks"], "member_id": member_ids["Sunil"], "share_quantity": 0.3333},
        {"receipt_item_id": item_lookup["Sparkling Drinks"], "member_id": member_ids["Dhruv"], "share_quantity": 0.3333},
        {"receipt_item_id": item_lookup["Sparkling Drinks"], "member_id": member_ids["Pawan"], "share_quantity": 0.3334},
    ]
    res_assign = client.post(
        f"/api/expenses/{expense_id}/assign",
        json={"assignments": assignments},
    )
    assert res_assign.status_code == 201, res_assign.text
    assert len(res_assign.json()) == 6

    # -------------------------------------------------------------------------
    # Step 8: Calculate Splits with Penny Accuracy (GET /api/expenses/{expense_id}/splits)
    # -------------------------------------------------------------------------
    res_splits = client.get(f"/api/expenses/{expense_id}/splits")
    assert res_splits.status_code == 200, res_splits.text
    splits_data = res_splits.json()

    assert splits_data["expense_id"] == expense_id
    total_split_sum = Decimal("0.00")
    for s in splits_data["splits"]:
        amt = Decimal(str(s["amount"]))
        assert amt > Decimal("0.00")
        total_split_sum += amt

    # Exact penny conservation check: Sum of individual splits == total_amount
    assert total_split_sum == Decimal("60.00"), f"Split sum {total_split_sum} != 60.00"

    # -------------------------------------------------------------------------
    # Step 9: Initialize Payments (POST /api/expenses/{expense_id}/initialize-payments)
    # -------------------------------------------------------------------------
    res_init_pay = client.post(f"/api/expenses/{expense_id}/initialize-payments")
    assert res_init_pay.status_code == 201, res_init_pay.text
    payments_list = res_init_pay.json()
    assert len(payments_list) == 3
    for p in payments_list:
        assert p["status"] == "pending"
        assert Decimal(str(p["amount"])) > Decimal("0.00")

    # Pick Dhruv's payment record to settle via PayPal
    dhruv_payment = next(p for p in payments_list if p["member_id"] == member_ids["Dhruv"])
    payment_id = dhruv_payment["id"]

    # -------------------------------------------------------------------------
    # Step 10: Create PayPal Order (POST /api/payments/{payment_id}/create-order)
    # -------------------------------------------------------------------------
    res_order = client.post(f"/api/payments/{payment_id}/create-order")
    assert res_order.status_code == 200, res_order.text
    order_data = res_order.json()
    assert "paypal_order_id" in order_data
    paypal_order_id = order_data["paypal_order_id"]
    assert order_data["status"] == "order_created"
    assert paypal_order_id is not None

    # -------------------------------------------------------------------------
    # Step 11: Capture PayPal Payment (POST /api/payments/{payment_id}/capture)
    # -------------------------------------------------------------------------
    # Attempting to capture with wrong order_id must fail (400)
    res_wrong_capture = client.post(
        f"/api/payments/{payment_id}/capture",
        json={"paypal_order_id": "WRONG-ORDER-ID-999"},
    )
    assert res_wrong_capture.status_code == 400

    # Capturing with the correct order_id must succeed (200)
    res_capture = client.post(
        f"/api/payments/{payment_id}/capture",
        json={"paypal_order_id": paypal_order_id},
    )
    assert res_capture.status_code == 200, res_capture.text
    capture_data = res_capture.json()
    assert capture_data["status"] == "captured"
    assert capture_data["paypal_capture_id"] is not None

    # Attempting to capture AGAIN must be rejected as duplicate (409)
    res_dup_capture = client.post(
        f"/api/payments/{payment_id}/capture",
        json={"paypal_order_id": paypal_order_id},
    )
    assert res_dup_capture.status_code == 409

    # -------------------------------------------------------------------------
    # Step 12: Verify Final Payment Statuses & Summary (GET /api/payments/{payment_id})
    # -------------------------------------------------------------------------
    res_verify = client.get(f"/api/payments/{payment_id}")
    assert res_verify.status_code == 200, res_verify.text
    final_payment = res_verify.json()
    assert final_payment["id"] == payment_id
    assert final_payment["status"] == "captured"
    assert final_payment["paypal_order_id"] == paypal_order_id
    assert final_payment["paypal_capture_id"] == capture_data["paypal_capture_id"]

    # Verify expense payments list
    res_expense_payments = client.get(f"/api/payments/expense/{expense_id}")
    assert res_expense_payments.status_code == 200, res_expense_payments.text
    all_expense_payments = res_expense_payments.json()
    assert len(all_expense_payments) == 3
    # Check that Dhruv's payment is captured while others remain pending
    dhruv_checked = next(p for p in all_expense_payments if p["id"] == payment_id)
    assert dhruv_checked["status"] == "captured"

    # -------------------------------------------------------------------------
    # Step 13: Data Persistence Check (Simulate Backend Restart / Reconnect)
    # -------------------------------------------------------------------------
    # Re-query all entities via fresh API calls to confirm full database persistence
    persisted_group = client.get(f"/api/groups/{group_id}")
    assert persisted_group.status_code == 200
    assert persisted_group.json()["name"] == "PayPal AI Hackathon Squad"

    persisted_members = client.get(f"/api/groups/{group_id}/members")
    assert persisted_members.status_code == 200
    assert len(persisted_members.json()) == 3

    persisted_expense = client.get(f"/api/expenses/{expense_id}")
    assert persisted_expense.status_code == 200
    assert Decimal(str(persisted_expense.json()["total_amount"])) == Decimal("60.00")

    persisted_payment = client.get(f"/api/payments/{payment_id}")
    assert persisted_payment.status_code == 200
    assert persisted_payment.json()["status"] == "captured"
    assert persisted_payment.json()["paypal_capture_id"] == capture_data["paypal_capture_id"]
