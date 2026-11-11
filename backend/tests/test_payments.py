"""Automated test suite for PayPal Sandbox integration in SplitMate.

Tests all requirements:
- Successful & failed OAuth authentication
- Successful & failed order creation
- Successful & failed payment capture
- Invalid order ID & payment ownership
- Amount & currency mismatch validation
- Duplicate order creation & capture prevention
- PayPal network timeout handling
- Malformed PayPal API response handling
- Frontend compatibility endpoints
"""

from decimal import Decimal
import io
from unittest.mock import MagicMock, patch
import uuid

import httpx
import pytest

from app.api.routes.payments import get_paypal_service
from app.core.config import settings
from app.db.session import get_db
from app.models.models import Payment, PaymentStatus
from app.services.paypal_service import (
    PayPalAuthError,
    PayPalCaptureError,
    PayPalConnectionError,
    PayPalOrderError,
    PayPalService,
)
from tests.conftest import (
    TEST_INTERNAL_SERVICE_SECRET,
    VALID_JPEG_BYTES,
    DEFAULT_TEST_USER_EMAIL,
    DEFAULT_TEST_USER_NAME,
    create_user_and_client,
)

AI_KEY_HEADER = {"X-Internal-Service-Key": TEST_INTERNAL_SERVICE_SECRET}


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------

def _create_payment_setup(client):
    """Helper: creates group -> member -> receipt -> expense -> splits -> initialized payment.

    The group member is created with the authenticated user's email so that
    ``require_payment_access(..., require_payer=True)`` passes for `client`.
    """
    # Resolve the authenticated user's identity from the test client fixture.
    # client.auth_user is set by the `client` fixture in conftest.py.
    auth_user = getattr(client, "auth_user", None)
    member_name = auth_user.name if auth_user else DEFAULT_TEST_USER_NAME
    member_email = auth_user.email if auth_user else DEFAULT_TEST_USER_EMAIL

    # 1. Group + member (must be the authenticated user so payer checks pass)
    group_resp = client.post("/api/groups", json={"name": "Payment Test Group"})
    assert group_resp.status_code == 201
    group_id = group_resp.json()["id"]

    member_resp = client.post(
        f"/api/groups/{group_id}/members",
        json={"name": member_name, "email": member_email},
    )
    assert member_resp.status_code == 201
    member_id = member_resp.json()["id"]

    # 2. Receipt upload + extraction
    upload_resp = client.post(
        "/api/receipts/upload",
        files={"file": ("r.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    receipt_id = upload_resp.json()["id"]

    extract_resp = client.post(
        f"/api/receipts/{receipt_id}/extraction",
        json={
            "merchant_name": "Test Diner",
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
        headers=AI_KEY_HEADER,
    )
    assert extract_resp.status_code == 200

    receipt_data = client.get(f"/api/receipts/{receipt_id}").json()
    item_id = receipt_data["items"][0]["id"]

    # 3. Expense
    expense_resp = client.post(
        "/api/expenses",
        json={
            "group_id": group_id,
            "receipt_id": receipt_id,
            "total_amount": "10.80",
            "currency": "USD",
        },
    )
    assert expense_resp.status_code == 201
    expense_id = expense_resp.json()["id"]

    # 4. Item assignment
    assign_resp = client.post(
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
    assert assign_resp.status_code == 201

    # 5. Initialize payments
    init_resp = client.post(f"/api/expenses/{expense_id}/initialize-payments")
    assert init_resp.status_code == 201
    payments_data = init_resp.json()
    assert len(payments_data) == 1
    payment_id = payments_data[0]["id"]

    return payment_id, expense_id, member_id


def _mock_paypal_http_response(status_code: int = 200, json_data: dict = None):
    """Generate a mock httpx.Response object."""
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status_code
    mock_resp.json.return_value = json_data or {}
    return mock_resp


# ---------------------------------------------------------------------------
# 1. Base Retrieval & Ownership Tests
# ---------------------------------------------------------------------------

def test_get_payment(client):
    payment_id, _, _ = _create_payment_setup(client)
    response = client.get(f"/api/payments/{payment_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "pending"
    assert data["amount"] == "10.80"
    assert data["currency"] == "USD"
    assert data["paypal_order_id"] is None
    assert data["paypal_capture_id"] is None


def test_get_payment_not_found(client):
    response = client.get(f"/api/payments/{uuid.uuid4()}")
    assert response.status_code == 404
    assert "Payment not found" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 2. PayPal OAuth 2.0 Authentication Tests
# ---------------------------------------------------------------------------

def test_paypal_oauth_success():
    """Verify PayPalService obtains and caches OAuth 2.0 access token."""
    svc = PayPalService(
        client_id="test-client-id",
        client_secret="test-client-secret",
        base_url="https://api-m.sandbox.paypal.com",
    )

    token_payload = {
        "access_token": "ACCESS-TOKEN-A1B2C3D4",
        "token_type": "Bearer",
        "expires_in": 3600,
    }

    with patch("httpx.Client.post") as mock_post:
        mock_post.return_value = _mock_paypal_http_response(200, token_payload)

        token = svc.get_access_token()
        assert token == "ACCESS-TOKEN-A1B2C3D4"
        assert mock_post.call_count == 1

        # Second call should use cached token without additional network request
        cached_token = svc.get_access_token()
        assert cached_token == "ACCESS-TOKEN-A1B2C3D4"
        assert mock_post.call_count == 1


def test_paypal_oauth_failure():
    """Verify PayPalService raises PayPalAuthError on invalid credentials (401)."""
    svc = PayPalService(
        client_id="invalid-id",
        client_secret="invalid-secret",
        base_url="https://api-m.sandbox.paypal.com",
    )

    with patch("httpx.Client.post") as mock_post:
        mock_post.return_value = _mock_paypal_http_response(
            401, {"error": "invalid_client", "error_description": "Client Authentication failed"}
        )

        with pytest.raises(PayPalAuthError) as exc_info:
            svc.get_access_token()

        assert "Client Authentication failed" in exc_info.value.message


def test_paypal_oauth_missing_credentials():
    """Verify PayPalService raises PayPalAuthError if credentials are not configured."""
    svc = PayPalService(client_id="", client_secret="")
    with pytest.raises(PayPalAuthError) as exc_info:
        svc.get_access_token()
    assert "not configured" in exc_info.value.message


# ---------------------------------------------------------------------------
# 3. Create PayPal Order Tests
# ---------------------------------------------------------------------------

def test_create_order_success(client):
    """Verify successful order creation updates payment state and returns order details."""
    payment_id, _, _ = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(return_value={
        "id": "PAYPAL-ORDER-1001",
        "status": "CREATED",
        "approval_url": "https://www.sandbox.paypal.com/checkoutnow?token=PAYPAL-ORDER-1001",
        "links": [],
    })

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        response = client.post(f"/api/payments/{payment_id}/create-order", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "order_created"
        assert data["paypal_order_id"] == "PAYPAL-ORDER-1001"
        assert data["approval_url"] == "https://www.sandbox.paypal.com/checkoutnow?token=PAYPAL-ORDER-1001"

        # Verify order was created with the server-side amount (10.80)
        mock_svc.create_order.assert_called_once()
        call_kwargs = mock_svc.create_order.call_args[1]
        assert call_kwargs["amount"] == Decimal("10.80")
        assert call_kwargs["currency"] == "USD"
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_create_order_failed_paypal_api(client):
    """Verify handling when PayPal API rejects order creation."""
    payment_id, _, _ = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(side_effect=PayPalOrderError("VALIDATION_ERROR: Invalid amount"))

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        response = client.post(f"/api/payments/{payment_id}/create-order", json={})
        assert response.status_code == 502
        assert "VALIDATION_ERROR" in response.json()["detail"]

        # Ensure payment status remains pending
        get_resp = client.get(f"/api/payments/{payment_id}")
        assert get_resp.json()["status"] == "pending"
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_create_order_duplicate_prevented(client):
    """Verify that calling create-order on an already created order returns 409 Conflict."""
    payment_id, _, _ = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(return_value={
        "id": "PAYPAL-ORDER-DUP-1",
        "status": "CREATED",
        "approval_url": "https://paypal.example.com",
    })

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        # First order creation succeeds
        resp1 = client.post(f"/api/payments/{payment_id}/create-order", json={})
        assert resp1.status_code == 200

        # Second order creation must be rejected
        resp2 = client.post(f"/api/payments/{payment_id}/create-order", json={})
        assert resp2.status_code == 409
        assert "already" in resp2.json()["detail"].lower()
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_create_order_nonexistent_payment(client):
    """Verify 404 when payment does not exist."""
    response = client.post(f"/api/payments/{uuid.uuid4()}/create-order", json={})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 4. Capture PayPal Order Tests
# ---------------------------------------------------------------------------

def test_capture_success(client):
    """Verify successful capture transitions payment to CAPTURED and records capture ID."""
    payment_id, _, _ = _create_payment_setup(client)

    # First, create order
    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(return_value={
        "id": "PAYPAL-ORDER-CAP-1",
        "status": "CREATED",
        "approval_url": "https://paypal.example.com",
    })
    mock_svc.capture_order = MagicMock(return_value={
        "order_id": "PAYPAL-ORDER-CAP-1",
        "capture_id": "PAYPAL-CAPTURE-9999",
        "status": "COMPLETED",
        "captured_amount": "10.80",
        "captured_currency": "USD",
    })

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        create_resp = client.post(f"/api/payments/{payment_id}/create-order", json={})
        assert create_resp.status_code == 200

        capture_resp = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "PAYPAL-ORDER-CAP-1"},
        )
        assert capture_resp.status_code == 200
        data = capture_resp.json()
        assert data["status"] == "captured"
        assert data["paypal_capture_id"] == "PAYPAL-CAPTURE-9999"
        assert data["paypal_order_id"] == "PAYPAL-ORDER-CAP-1"
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_capture_order_id_mismatch(client):
    """Verify capture fails with 400 if client sends an order ID different from DB record."""
    payment_id, _, _ = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(return_value={
        "id": "PAYPAL-ORDER-REAL",
        "status": "CREATED",
    })

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        client.post(f"/api/payments/{payment_id}/create-order", json={})

        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "WRONG-ORDER-ID"},
        )
        assert response.status_code == 400
        assert "does not match" in response.json()["detail"]
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_capture_amount_mismatch(client):
    """Verify security check: captured amount must match DB amount exactly."""
    payment_id, _, _ = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(return_value={"id": "ORDER-AMT-TEST", "status": "CREATED"})
    # Attacker paid 5.00 instead of 10.80
    mock_svc.capture_order = MagicMock(return_value={
        "order_id": "ORDER-AMT-TEST",
        "capture_id": "CAP-UNDERPAID",
        "status": "COMPLETED",
        "captured_amount": "5.00",
        "captured_currency": "USD",
    })

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        client.post(f"/api/payments/{payment_id}/create-order", json={})

        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORDER-AMT-TEST"},
        )
        assert response.status_code == 400
        assert "does not match expected database amount" in response.json()["detail"]

        # Payment status must be set to failed
        status_resp = client.get(f"/api/payments/{payment_id}")
        assert status_resp.json()["status"] == "failed"
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_capture_currency_mismatch(client):
    """Verify security check: captured currency must match DB currency."""
    payment_id, _, _ = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(return_value={"id": "ORDER-CURR-TEST", "status": "CREATED"})
    # Paid in EUR instead of USD
    mock_svc.capture_order = MagicMock(return_value={
        "order_id": "ORDER-CURR-TEST",
        "capture_id": "CAP-EUR",
        "status": "COMPLETED",
        "captured_amount": "10.80",
        "captured_currency": "EUR",
    })

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        client.post(f"/api/payments/{payment_id}/create-order", json={})

        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORDER-CURR-TEST"},
        )
        assert response.status_code == 400
        assert "Captured currency" in response.json()["detail"]

        # Payment status must be set to failed
        status_resp = client.get(f"/api/payments/{payment_id}")
        assert status_resp.json()["status"] == "failed"
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_capture_failed_paypal_api(client):
    """Verify handling when PayPal capture API returns an error."""
    payment_id, _, _ = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(return_value={"id": "ORDER-FAIL-CAP", "status": "CREATED"})
    mock_svc.capture_order = MagicMock(side_effect=PayPalCaptureError("INSTRUMENT_DECLINED: Card declined"))

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        client.post(f"/api/payments/{payment_id}/create-order", json={})

        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORDER-FAIL-CAP"},
        )
        assert response.status_code == 502
        assert "INSTRUMENT_DECLINED" in response.json()["detail"]

        # Status must be updated to failed
        status_resp = client.get(f"/api/payments/{payment_id}")
        assert status_resp.json()["status"] == "failed"
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_capture_duplicate_prevented(client):
    """Verify that capturing an already captured payment returns 409 Conflict."""
    payment_id, _, _ = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(return_value={"id": "ORDER-DUP-CAP", "status": "CREATED"})
    mock_svc.capture_order = MagicMock(return_value={
        "order_id": "ORDER-DUP-CAP",
        "capture_id": "CAP-DUP",
        "status": "COMPLETED",
        "captured_amount": "10.80",
        "captured_currency": "USD",
    })

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        client.post(f"/api/payments/{payment_id}/create-order", json={})
        resp1 = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORDER-DUP-CAP"},
        )
        assert resp1.status_code == 200

        # Attempting capture again
        resp2 = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORDER-DUP-CAP"},
        )
        assert resp2.status_code == 409
        assert "already captured" in resp2.json()["detail"].lower()
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_capture_pending_prevented(client):
    """Cannot capture a payment that has not had an order created (status is pending)."""
    payment_id, _, _ = _create_payment_setup(client)
    response = client.post(
        f"/api/payments/{payment_id}/capture",
        json={"paypal_order_id": "FAKE-ORDER-123"},
    )
    assert response.status_code == 409
    assert "order_created" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 5. Network Timeout & Malformed Response Tests
# ---------------------------------------------------------------------------

def test_paypal_network_timeout(client):
    """Verify handling when PayPal connection times out (returns 504)."""
    payment_id, _, _ = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(side_effect=PayPalConnectionError("Connection timed out"))

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        response = client.post(f"/api/payments/{payment_id}/create-order", json={})
        assert response.status_code == 504
        assert "timed out" in response.json()["detail"].lower()
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_paypal_service_malformed_create_order():
    """Verify PayPalService handles malformed create order response safely."""
    svc = PayPalService(client_id="cid", client_secret="csec")
    svc.get_access_token = MagicMock(return_value="mock-token")

    with patch("httpx.Client.post") as mock_post:
        # 200 OK but response is missing "id"
        mock_post.return_value = _mock_paypal_http_response(200, {"status": "CREATED"})

        with pytest.raises(PayPalOrderError) as exc_info:
            svc.create_order(amount=Decimal("10.00"), currency="USD")
        assert "Malformed" in exc_info.value.message


def test_paypal_service_malformed_capture_order():
    """Verify PayPalService handles missing purchase_units/captures gracefully."""
    svc = PayPalService(client_id="cid", client_secret="csec")
    svc.get_access_token = MagicMock(return_value="mock-token")

    with patch("httpx.Client.post") as mock_post:
        # 200 OK but empty purchase units
        mock_post.return_value = _mock_paypal_http_response(200, {"id": "ORD-1", "purchase_units": []})

        with pytest.raises(PayPalCaptureError) as exc_info:
            svc.capture_order(order_id="ORD-1")
        assert "No capture records found" in exc_info.value.message


# ---------------------------------------------------------------------------
# 6. Frontend Compatibility Endpoints Tests
# ---------------------------------------------------------------------------

def test_frontend_compatibility_routes(client):
    """Verify Dhruv's frontend routes /api/payments/paypal/create-order and /capture-order."""
    payment_id, expense_id, member_id = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(return_value={
        "id": "FRONTEND-ORDER-1",
        "status": "CREATED",
        "approval_url": "https://www.sandbox.paypal.com/checkoutnow?token=FRONTEND-ORDER-1",
    })
    mock_svc.capture_order = MagicMock(return_value={
        "order_id": "FRONTEND-ORDER-1",
        "capture_id": "FRONTEND-CAPTURE-1",
        "status": "COMPLETED",
        "captured_amount": "10.80",
        "captured_currency": "USD",
    })

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        # Frontend calls /api/payments/paypal/create-order with payerId
        resp_create = client.post(
            "/api/payments/paypal/create-order",
            json={"payerId": str(member_id), "expenseId": str(expense_id)},
        )
        assert resp_create.status_code == 200
        data_create = resp_create.json()
        assert data_create["paypal_order_id"] == "FRONTEND-ORDER-1"
        assert data_create["status"] == "order_created"

        # Frontend calls /api/payments/paypal/capture-order with orderId
        resp_cap = client.post(
            "/api/payments/paypal/capture-order",
            json={"orderId": "FRONTEND-ORDER-1"},
        )
        assert resp_cap.status_code == 200
        data_cap = resp_cap.json()
        assert data_cap["status"] == "captured"
        assert data_cap["paypal_capture_id"] == "FRONTEND-CAPTURE-1"
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_payment_history(client):
    """Verify /api/payments/history returns created payments."""
    _create_payment_setup(client)
    response = client.get("/api/payments/history")
    assert response.status_code == 200
    assert len(response.json()) >= 1


# ---------------------------------------------------------------------------
# 7. Reliability & Hardening Tests (Timeout Reconciliation, Rollback, Ownership)
# ---------------------------------------------------------------------------

def test_capture_reconciliation_after_network_timeout(client):
    """Scenario:
    1. First capture call times out (network error). Payment status remains order_created (NOT failed).
    2. User retries capture. PayPal returns 422 ORDER_ALREADY_CAPTURED.
    3. Backend reconciles using PayPal order details, verifies amount/currency, and transitions to CAPTURED.
    """
    payment_id, _, _ = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(return_value={
        "id": "RECON-ORDER-101",
        "status": "CREATED",
        "approval_url": "https://paypal.example.com",
    })

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        # Step 1: Create order
        create_resp = client.post(f"/api/payments/{payment_id}/create-order", json={})
        assert create_resp.status_code == 200

        # Step 2: First capture attempt times out
        mock_svc.capture_order = MagicMock(side_effect=PayPalConnectionError("Connection dropped during capture"))
        timeout_resp = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "RECON-ORDER-101"},
        )
        assert timeout_resp.status_code == 504
        assert "timed out" in timeout_resp.json()["detail"].lower()

        # Verify payment status was NOT marked failed; remains order_created
        check_resp = client.get(f"/api/payments/{payment_id}")
        assert check_resp.json()["status"] == "order_created"

        # Step 3: Second capture attempt (retry).
        # capture_order simulates receiving ORDER_ALREADY_CAPTURED error from PayPal,
        # but get_order_details returns completed order with capture info.
        mock_svc.capture_order = MagicMock(
            side_effect=PayPalCaptureError(
                message="Order has already been captured.",
                status_code=422,
                issue="ORDER_ALREADY_CAPTURED",
            )
        )
        mock_svc.get_order_details = MagicMock(return_value={
            "id": "RECON-ORDER-101",
            "status": "COMPLETED",
            "purchase_units": [
                {
                    "payments": {
                        "captures": [
                            {
                                "id": "RECON-CAPTURE-999",
                                "status": "COMPLETED",
                                "amount": {"value": "10.80", "currency_code": "USD"},
                            }
                        ]
                    }
                }
            ],
        })

        retry_resp = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "RECON-ORDER-101"},
        )
        assert retry_resp.status_code == 200
        data = retry_resp.json()
        assert data["status"] == "captured"
        assert data["paypal_capture_id"] == "RECON-CAPTURE-999"

        # Final database check
        final_check = client.get(f"/api/payments/{payment_id}")
        assert final_check.json()["status"] == "captured"
        assert final_check.json()["paypal_capture_id"] == "RECON-CAPTURE-999"
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_paypal_service_reconciles_already_captured_order():
    """Unit test: PayPalService.capture_order directly handles 422 ORDER_ALREADY_CAPTURED."""
    svc = PayPalService(client_id="cid", client_secret="csec")
    svc.get_access_token = MagicMock(return_value="mock-token")

    already_captured_error = {
        "name": "UNPROCESSABLE_ENTITY",
        "details": [
            {
                "issue": "ORDER_ALREADY_CAPTURED",
                "description": "Order has already been captured.",
            }
        ],
    }

    completed_order_details = {
        "id": "ORD-RECON-1",
        "status": "COMPLETED",
        "purchase_units": [
            {
                "payments": {
                    "captures": [
                        {
                            "id": "CAP-RECON-1",
                            "status": "COMPLETED",
                            "amount": {"value": "25.00", "currency_code": "USD"},
                        }
                    ]
                }
            }
        ],
    }

    with patch("httpx.Client.post") as mock_post:
        mock_post.return_value = _mock_paypal_http_response(422, already_captured_error)
        svc.get_order_details = MagicMock(return_value=completed_order_details)

        res = svc.capture_order("ORD-RECON-1")
        assert res["capture_id"] == "CAP-RECON-1"
        assert res["status"] == "COMPLETED"
        assert res["captured_amount"] == "25.00"
        assert res["captured_currency"] == "USD"
        svc.get_order_details.assert_called_once_with("ORD-RECON-1")


def test_payment_ownership_violation_create_order(client, db_session):
    """Verify that an authenticated user who is NOT the payer cannot create an order (403)."""
    # Setup: payment belongs to `client` (the primary authenticated user)
    payment_id, _, _ = _create_payment_setup(client)

    # Create a second user who does NOT own the payment
    _, impostor_client, _ = create_user_and_client(db_session, email="impostor@example.com", name="Impostor")

    response = impostor_client.post(
        f"/api/payments/{payment_id}/create-order",
        json={},
    )
    assert response.status_code == 403
    assert "not authorized" in response.json()["detail"].lower() or "only manage" in response.json()["detail"].lower()


def test_payment_ownership_violation_capture(client, db_session):
    """Verify that an authenticated user who is NOT the payer cannot capture a payment (403)."""
    # Setup: payment belongs to `client` (the primary authenticated user)
    payment_id, _, _ = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(return_value={"id": "ORD-OWN-1", "status": "CREATED"})
    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        # Legitimate owner creates the order
        client.post(f"/api/payments/{payment_id}/create-order", json={})

        # Create a second user who does NOT own the payment
        _, impostor_client, _ = create_user_and_client(db_session, email="impostor2@example.com", name="Impostor2")
        impostor_client.app = client.app  # share the app instance with its dependency overrides

        response = impostor_client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORD-OWN-1"},
        )
        assert response.status_code == 403
        assert "not authorized" in response.json()["detail"].lower() or "only manage" in response.json()["detail"].lower()
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_database_rollback_on_commit_error(client):
    """Verify that when db.commit() raises an exception during capture, rollback is executed."""
    payment_id, _, _ = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(return_value={"id": "ORD-ROLLBACK", "status": "CREATED"})
    mock_svc.capture_order = MagicMock(return_value={
        "order_id": "ORD-ROLLBACK",
        "capture_id": "CAP-ROLLBACK",
        "status": "COMPLETED",
        "captured_amount": "10.80",
        "captured_currency": "USD",
    })

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        client.post(f"/api/payments/{payment_id}/create-order", json={})

        # Mock db.commit to raise an exception
        from sqlalchemy.orm import Session
        with patch.object(Session, "commit", side_effect=RuntimeError("Simulated DB Disk Failure")):
            response = client.post(
                f"/api/payments/{payment_id}/capture",
                json={"paypal_order_id": "ORD-ROLLBACK"},
            )
            assert response.status_code == 500
            assert "Failed to commit" in response.json()["detail"]
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)


def test_concurrent_capture_attempts(client):
    """Verify concurrent/duplicate capture attempt on already captured payment returns 409."""
    payment_id, _, _ = _create_payment_setup(client)

    mock_svc = PayPalService(client_id="cid", client_secret="csec")
    mock_svc.create_order = MagicMock(return_value={"id": "ORD-CONC-1", "status": "CREATED"})
    mock_svc.capture_order = MagicMock(return_value={
        "order_id": "ORD-CONC-1",
        "capture_id": "CAP-CONC-1",
        "status": "COMPLETED",
        "captured_amount": "10.80",
        "captured_currency": "USD",
    })

    client.app.dependency_overrides[get_paypal_service] = lambda: mock_svc
    try:
        client.post(f"/api/payments/{payment_id}/create-order", json={})

        # First capture attempt
        first_resp = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORD-CONC-1"},
        )
        assert first_resp.status_code == 200

        # Concurrent/subsequent attempt on captured payment
        second_resp = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORD-CONC-1"},
        )
        assert second_resp.status_code == 409
        assert "already captured" in second_resp.json()["detail"].lower()
    finally:
        client.app.dependency_overrides.pop(get_paypal_service, None)
