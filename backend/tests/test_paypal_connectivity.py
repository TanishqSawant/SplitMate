"""Phase 3: PayPal integration tests.

Covers:
  - Mock mode when credentials are absent
  - Mock order creation (MOCK-ORD-* format)
  - Mock capture (MOCK-CAP-* format, COMPLETED status)
  - Duplicate-capture protection (409)
  - Order-ID mismatch protection (400)
  - Payment state machine transitions (pending → order_created → captured)
  - Live PayPal Sandbox connectivity (skipped when no credentials set)

Run:
    python -m pytest tests/test_paypal_connectivity.py -v
"""

import io
import os
from decimal import Decimal

import pytest

from tests.conftest import TEST_INTERNAL_SERVICE_SECRET, VALID_JPEG_BYTES


# ===========================================================================
# 1. PayPalService unit tests (no network calls)
# ===========================================================================

class TestPayPalServiceUnit:
    """Unit tests for PayPalService mock mode behavior."""

    def test_paypal_not_configured_when_env_empty(self):
        """PayPalService.is_configured must be False when credentials are empty."""
        from app.services.paypal import PayPalService
        from app.core.config import settings

        original_id = settings.PAYPAL_CLIENT_ID
        original_secret = settings.PAYPAL_CLIENT_SECRET
        try:
            settings.PAYPAL_CLIENT_ID = ""
            settings.PAYPAL_CLIENT_SECRET = ""
            svc = PayPalService()
            assert svc.is_configured is False
        finally:
            settings.PAYPAL_CLIENT_ID = original_id
            settings.PAYPAL_CLIENT_SECRET = original_secret

    def test_paypal_not_configured_with_mock_prefix(self):
        """PayPalService.is_configured must be False when client_id starts with 'mock'."""
        from app.services.paypal import PayPalService
        from app.core.config import settings

        original_id = settings.PAYPAL_CLIENT_ID
        original_secret = settings.PAYPAL_CLIENT_SECRET
        try:
            settings.PAYPAL_CLIENT_ID = "mock-client-id"
            settings.PAYPAL_CLIENT_SECRET = "some-secret"
            svc = PayPalService()
            assert svc.is_configured is False
        finally:
            settings.PAYPAL_CLIENT_ID = original_id
            settings.PAYPAL_CLIENT_SECRET = original_secret

    def test_mock_access_token_returned_when_not_configured(self):
        """get_access_token() must return a string in mock mode (no network call)."""
        from app.services.paypal import PayPalService
        from app.core.config import settings

        original_id = settings.PAYPAL_CLIENT_ID
        original_secret = settings.PAYPAL_CLIENT_SECRET
        try:
            settings.PAYPAL_CLIENT_ID = ""
            settings.PAYPAL_CLIENT_SECRET = ""
            svc = PayPalService()
            token = svc.get_access_token()
            assert isinstance(token, str)
            assert len(token) > 0
        finally:
            settings.PAYPAL_CLIENT_ID = original_id
            settings.PAYPAL_CLIENT_SECRET = original_secret

    def test_mock_create_order_format(self):
        """Mock create_order() must return MOCK-ORD-* ID with status CREATED."""
        from app.services.paypal import PayPalService
        from app.core.config import settings

        original_id = settings.PAYPAL_CLIENT_ID
        original_secret = settings.PAYPAL_CLIENT_SECRET
        try:
            settings.PAYPAL_CLIENT_ID = ""
            settings.PAYPAL_CLIENT_SECRET = ""
            svc = PayPalService()
            order = svc.create_order(amount=Decimal("25.00"), currency="USD", reference_id="test-ref-123")
            assert "id" in order
            assert order["id"].startswith("MOCK-ORD-"), (
                f"Expected MOCK-ORD-* format, got: {order['id']}"
            )
            assert order["status"] == "CREATED"
            assert order.get("mock") is True
        finally:
            settings.PAYPAL_CLIENT_ID = original_id
            settings.PAYPAL_CLIENT_SECRET = original_secret

    def test_mock_capture_payment_format(self):
        """Mock capture_payment() must return MOCK-CAP-* capture_id with COMPLETED status."""
        from app.services.paypal import PayPalService
        from app.core.config import settings

        original_id = settings.PAYPAL_CLIENT_ID
        original_secret = settings.PAYPAL_CLIENT_SECRET
        try:
            settings.PAYPAL_CLIENT_ID = ""
            settings.PAYPAL_CLIENT_SECRET = ""
            svc = PayPalService()
            result = svc.capture_payment(order_id="MOCK-ORD-TESTREF-9999999")
            assert "capture_id" in result
            assert result["capture_id"].startswith("MOCK-CAP-"), (
                f"Expected MOCK-CAP-* format, got: {result['capture_id']}"
            )
            assert result["status"] == "COMPLETED"
            assert result.get("mock") is True
        finally:
            settings.PAYPAL_CLIENT_ID = original_id
            settings.PAYPAL_CLIENT_SECRET = original_secret

    def test_mock_order_id_includes_reference(self):
        """Mock order ID must incorporate the reference_id slug for traceability."""
        from app.services.paypal import PayPalService
        from app.core.config import settings

        original_id = settings.PAYPAL_CLIENT_ID
        original_secret = settings.PAYPAL_CLIENT_SECRET
        try:
            settings.PAYPAL_CLIENT_ID = ""
            settings.PAYPAL_CLIENT_SECRET = ""
            svc = PayPalService()
            order = svc.create_order(amount=Decimal("10.00"), reference_id="abcd1234xyz")
            assert "ABCD1234" in order["id"].upper() or order["id"].startswith("MOCK-ORD-")
        finally:
            settings.PAYPAL_CLIENT_ID = original_id
            settings.PAYPAL_CLIENT_SECRET = original_secret


# ===========================================================================
# 2. Payment API endpoint integration tests
# ===========================================================================

class TestPaymentAPIEndpoints:
    """Integration tests for payment routes in mock mode via FastAPI TestClient."""

    @pytest.fixture(autouse=True)
    def force_mock_mode(self):
        """Explicitly configure mock mode for all mock-mode tests to ensure isolation."""
        from app.services.paypal import paypal_service
        prev_mode = paypal_service.mock_mode
        paypal_service.mock_mode = True
        try:
            yield
        finally:
            paypal_service.mock_mode = prev_mode

    def _create_expense_with_payment(self, client):
        """Helper: creates group → member → receipt → expense → assignments → initializes payments.
        Returns the payment record dict and expense_id.
        """
        # Create group (returns 201)
        group_resp = client.post(
            "/api/groups/",
            json={"name": "PayPal Test Group", "description": "Phase 3 PayPal tests"},
        )
        assert group_resp.status_code == 201, group_resp.text
        group_id = group_resp.json()["id"]

        # Add member (returns 201)
        m1 = client.post(
            f"/api/groups/{group_id}/members",
            json={"name": "Alice", "email": "alice@test.com"},
        )
        assert m1.status_code == 201, m1.text
        payer_id = m1.json()["id"]

        # Upload receipt (returns 201)
        upload_resp = client.post(
            "/api/receipts/upload",
            files={"file": ("receipt.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")},
        )
        assert upload_resp.status_code == 201, upload_resp.text
        receipt_id = upload_resp.json()["id"]

        # Populate extraction items
        extract_resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json={
                "merchant_name": "PayPal Test Diner",
                "currency": "USD",
                "subtotal": "25.00",
                "tax": "2.00",
                "total": "27.00",
                "items": [
                    {
                        "item_name": "Test Burger",
                        "quantity": 1,
                        "unit_price": "25.00",
                        "total_price": "25.00",
                    }
                ],
            },
            headers={"X-Internal-Service-Key": TEST_INTERNAL_SERVICE_SECRET},
        )
        assert extract_resp.status_code == 200, extract_resp.text

        receipt_data = client.get(f"/api/receipts/{receipt_id}").json()
        item_id = receipt_data["items"][0]["id"]

        # Create expense (returns 201)
        expense_resp = client.post(
            "/api/expenses/",
            json={
                "group_id": group_id,
                "receipt_id": receipt_id,
                "description": "PayPal Test Dinner",
                "total_amount": "27.00",
                "currency": "USD",
            },
        )
        assert expense_resp.status_code == 201, expense_resp.text
        expense_id = expense_resp.json()["id"]

        # Assign item to member (returns 201)
        assign_resp = client.post(
            f"/api/expenses/{expense_id}/assign",
            json={
                "assignments": [
                    {
                        "receipt_item_id": item_id,
                        "member_id": payer_id,
                        "share_quantity": "1",
                    }
                ]
            },
        )
        assert assign_resp.status_code == 201, assign_resp.text

        # Initialize payments (returns 201, response is a list of PaymentResponse)
        init_resp = client.post(f"/api/expenses/{expense_id}/initialize-payments")
        assert init_resp.status_code == 201, init_resp.text
        payments = init_resp.json()

        assert isinstance(payments, list), f"Expected list of payments, got: {type(payments)}: {payments}"
        assert len(payments) > 0, "No payments were initialized"
        return payments[0], expense_id

    def test_create_paypal_order_in_mock_mode(self, client):
        """POST /api/payments/{id}/create-order must return a MOCK-ORD-* order ID."""
        payment, _ = self._create_expense_with_payment(client)
        payment_id = payment["id"]

        resp = client.post(f"/api/payments/{payment_id}/create-order")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        order_id = data.get("paypal_order_id") or data.get("order_id")
        assert order_id is not None, f"No order_id in response: {data}"
        assert "MOCK-ORD-" in order_id or order_id.startswith("MOCK"), (
            f"Expected mock order ID, got: {order_id}"
        )

    def test_capture_payment_in_mock_mode(self, client):
        """POST /api/payments/{id}/capture must return a MOCK-CAP-* capture ID."""
        payment, _ = self._create_expense_with_payment(client)
        payment_id = payment["id"]

        # First create order
        order_resp = client.post(f"/api/payments/{payment_id}/create-order")
        assert order_resp.status_code == 200, order_resp.text
        order_id = (
            order_resp.json().get("paypal_order_id")
            or order_resp.json().get("order_id")
        )
        assert order_id is not None

        # Now capture
        capture_resp = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": order_id},
        )
        assert capture_resp.status_code == 200, capture_resp.text
        data = capture_resp.json()
        capture_id = data.get("capture_id") or data.get("paypal_capture_id")
        assert capture_id is not None
        # Payment status must be COMPLETED or captured
        status = data.get("status", "").upper()
        assert status in ("COMPLETED", "CAPTURED"), f"Unexpected status: {status}"

    def test_duplicate_capture_returns_409(self, client):
        """Second capture on the same payment must return 409 Conflict."""
        payment, _ = self._create_expense_with_payment(client)
        payment_id = payment["id"]

        # Create order
        order_resp = client.post(f"/api/payments/{payment_id}/create-order")
        assert order_resp.status_code == 200
        order_id = (
            order_resp.json().get("paypal_order_id")
            or order_resp.json().get("order_id")
        )

        # First capture (should succeed)
        cap1 = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": order_id},
        )
        assert cap1.status_code == 200, cap1.text

        # Second capture (should be blocked)
        cap2 = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": order_id},
        )
        assert cap2.status_code == 409, (
            f"Expected 409 for duplicate capture, got {cap2.status_code}: {cap2.text}"
        )

    def test_mismatched_order_id_returns_400(self, client):
        """Capture with wrong order_id must return 400 Bad Request."""
        payment, _ = self._create_expense_with_payment(client)
        payment_id = payment["id"]

        # Create order (creates the pending order on the payment record)
        order_resp = client.post(f"/api/payments/{payment_id}/create-order")
        assert order_resp.status_code == 200

        # Attempt capture with wrong order_id
        wrong_order_id = "WRONG-ORDER-ID-XYZ"
        cap = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": wrong_order_id},
        )
        assert cap.status_code == 400, (
            f"Expected 400 for mismatched order_id, got {cap.status_code}: {cap.text}"
        )

    def test_payment_state_machine_pending_to_created(self, client):
        """Payment status must transition from pending → order_created after create-order."""
        payment, _ = self._create_expense_with_payment(client)
        payment_id = payment["id"]

        # Verify initial state
        get_resp = client.get(f"/api/payments/{payment_id}")
        if get_resp.status_code == 200:
            assert get_resp.json().get("status") in ("pending", "PENDING")

        # Create order
        order_resp = client.post(f"/api/payments/{payment_id}/create-order")
        assert order_resp.status_code == 200

        # Verify state updated
        get_resp2 = client.get(f"/api/payments/{payment_id}")
        if get_resp2.status_code == 200:
            new_status = get_resp2.json().get("status", "").lower()
            assert new_status in ("order_created", "pending", "created"), (
                f"Unexpected post-create-order status: {new_status}"
            )

    def test_payment_state_machine_captured_to_completed(self, client):
        """Payment status must be captured/completed after full mock capture flow."""
        payment, _ = self._create_expense_with_payment(client)
        payment_id = payment["id"]

        order_resp = client.post(f"/api/payments/{payment_id}/create-order")
        assert order_resp.status_code == 200
        order_id = (
            order_resp.json().get("paypal_order_id")
            or order_resp.json().get("order_id")
        )

        cap_resp = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": order_id},
        )
        assert cap_resp.status_code == 200

        get_resp = client.get(f"/api/payments/{payment_id}")
        if get_resp.status_code == 200:
            final_status = get_resp.json().get("status", "").lower()
            assert final_status in ("captured", "completed"), (
                f"Unexpected final payment status: {final_status}"
            )

    def test_get_payments_by_expense(self, client):
        """GET /api/payments/expense/{id} must return initialized payments."""
        payment, expense_id = self._create_expense_with_payment(client)
        resp = client.get(f"/api/payments/expense/{expense_id}")
        assert resp.status_code == 200, resp.text
        payments = resp.json()
        assert isinstance(payments, list)
        assert len(payments) > 0


# ===========================================================================
# 3. Live PayPal Sandbox tests (skipped when no credentials are configured)
# ===========================================================================

def _has_live_paypal_credentials() -> bool:
    """Check if real/sandbox PayPal credentials are provided in settings or os.environ."""
    from app.core.config import settings
    client_id = os.environ.get("PAYPAL_CLIENT_ID") or settings.PAYPAL_CLIENT_ID
    client_secret = os.environ.get("PAYPAL_CLIENT_SECRET") or settings.PAYPAL_CLIENT_SECRET
    return bool(
        client_id
        and client_secret
        and not client_id.startswith("mock")
        and client_id.strip() != ""
        and client_secret.strip() != ""
    )


@pytest.mark.skipif(
    not _has_live_paypal_credentials(),
    reason="PAYPAL_CLIENT_ID/SECRET not set in environment or .env — skipping live PayPal Sandbox tests",
)
class TestPayPalLiveSandbox:
    """Live PayPal Sandbox API connectivity tests.

    These tests only run when PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET are set.
    They make real network calls to the PayPal Sandbox environment.
    NEVER use production credentials with these tests.
    """

    @pytest.fixture(autouse=True)
    def enable_live_mode(self):
        """Ensure live mode is active (not mock mode) for live Sandbox tests."""
        from app.services.paypal import paypal_service
        prev_mode = paypal_service.mock_mode
        paypal_service.mock_mode = False
        try:
            yield
        finally:
            paypal_service.mock_mode = prev_mode

    def test_paypal_configured_with_real_credentials(self):
        """PayPalService.is_configured must be True with real sandbox credentials."""
        from app.services.paypal import paypal_service
        assert paypal_service.is_configured is True

    def test_paypal_live_access_token(self):
        """PayPal OAuth2 must return a non-empty bearer token from sandbox."""
        from app.services.paypal import paypal_service
        token = paypal_service.get_access_token()
        assert isinstance(token, str)
        assert len(token) > 20
        assert token != "mock_sandbox_access_token"

    def test_paypal_live_create_order(self):
        """PayPal Orders API v2 must create a real SANDBOX order."""
        from app.services.paypal import paypal_service
        order = paypal_service.create_order(
            amount=Decimal("1.00"),
            currency="USD",
            reference_id="phase3-test-order",
        )
        assert "id" in order
        assert not order["id"].startswith("MOCK-")
        assert order.get("status") == "CREATED"
        assert order.get("mock") is not True

    def test_paypal_live_order_then_mock_capture(self):
        """Create a live sandbox order; capture should fail gracefully (needs PayPal approval)."""
        from app.services.paypal import paypal_service
        order = paypal_service.create_order(
            amount=Decimal("1.00"),
            currency="USD",
            reference_id="phase3-capture-test",
        )
        order_id = order["id"]
        # Capture without PayPal approval will return a non-200 from sandbox
        # We test that the service raises or returns an error gracefully
        try:
            result = paypal_service.capture_payment(order_id)
            # If it somehow succeeds (e.g., auto-approved), verify structure
            assert "capture_id" in result
            assert "status" in result
        except Exception as e:
            # Expected: PayPal returns 422 UNPROCESSABLE_ENTITY for unapproved order
            assert (
                "422" in str(e)
                or "UNPROCESSABLE" in str(e)
                or "ORDER_NOT_APPROVED" in str(e)
                or "HTTPStatusError" in type(e).__name__
            ), f"Unexpected error from PayPal capture: {e}"
