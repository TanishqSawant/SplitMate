"""Automated test suite for PayPal Sandbox integration in SplitMate.

Tests all requirements:
- Unit tests for PayPalService: OAuth token caching, credential validation,
  timeout handling, order creation, approval URL extraction, capture parsing,
  amount/currency validation, idempotency headers.
- API integration tests: Authenticated payer authorization (403 for other users),
  receipt extraction completion gate (400 if not completed), order creation state
  transitions, duplicate prevention (409), server-side capture verification
  (COMPLETED status, capture ID, amount & currency match), failure handling
  marking payment as FAILED (never CAPTURED), and sanitized error responses.
"""

from decimal import Decimal
import io
import time
from unittest.mock import MagicMock, patch
import uuid

import httpx
import pytest

from app.api.routes.payments import get_paypal_service
from app.db.session import get_db
from app.models.models import ExtractionStatus, Payment, PaymentStatus, Receipt
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
    create_user_and_client,
)

AI_KEY_HEADER = {"X-Internal-Service-Key": TEST_INTERNAL_SERVICE_SECRET}


# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_paypal_service(client):
    """Inject a mock PayPalService via FastAPI's dependency_overrides."""
    mock = MagicMock(spec=PayPalService)
    client.app.dependency_overrides[get_paypal_service] = lambda: mock
    yield mock
    client.app.dependency_overrides.pop(get_paypal_service, None)


def _create_payment_setup(client):
    """Helper: create group -> member -> receipt -> expense -> splits -> return payment ID."""
    user = getattr(client, "auth_user", None)
    member_name = user.name if user else "Alice"
    member_email = user.email if user else "alice@example.com"

    # 1. Group + member
    group_resp = client.post("/api/groups", json={"name": "Payment Test"})
    assert group_resp.status_code == 201
    group_id = group_resp.json()["id"]

    members_resp = client.get(f"/api/groups/{group_id}/members")
    members = members_resp.json()
    if members:
        member_id = members[0]["id"]
    else:
        member_resp = client.post(
            f"/api/groups/{group_id}/members",
            json={"name": member_name, "email": member_email},
        )
        member_id = member_resp.json()["id"]

    # 2. Receipt upload + extraction
    upload_resp = client.post(
        "/api/receipts/upload",
        files={"file": ("r.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")},
    )
    assert upload_resp.status_code == 201
    receipt_id = upload_resp.json()["receipt_id"]

    client.post(
        f"/api/receipts/{receipt_id}/extraction",
        json={
            "merchant_name": "Test Cafe",
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

    receipt_data = client.get(f"/api/receipts/{receipt_id}").json()
    item_id = receipt_data["items"][0]["id"]

    # 3. Expense (amount must match extracted total: 10.80)
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

    # 4. Assign and calculate split
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

    # 5. Initialize payment via POST /api/expenses/{expense_id}/initialize-payments
    init_resp = client.post(f"/api/expenses/{expense_id}/initialize-payments")
    assert init_resp.status_code == 201

    db_gen = client.app.dependency_overrides[get_db]()
    db = next(db_gen)
    payment = db.query(Payment).filter(Payment.expense_id == expense_id).first()
    return payment.id


# ===========================================================================
# 1. Unit Tests for PayPalService
# ===========================================================================

class TestPayPalServiceUnit:
    """Isolated unit tests for PayPalService methods and error conditions."""

    def test_oauth_token_success_and_caching(self):
        """Token is fetched on first call and reused from memory on subsequent calls."""
        service = PayPalService(
            client_id="test_client_id",
            client_secret="test_secret",
            base_url="https://api-m.sandbox.paypal.com",
            timeout=5.0,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "ACCESS_TOKEN_ABC123",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
            # 1st call -> network request
            token1 = service.get_access_token()
            assert token1 == "ACCESS_TOKEN_ABC123"
            assert mock_post.call_count == 1

            # 2nd call -> cached in-memory
            token2 = service.get_access_token()
            assert token2 == "ACCESS_TOKEN_ABC123"
            assert mock_post.call_count == 1

            # 3rd call with force_refresh -> new network request
            token3 = service.get_access_token(force_refresh=True)
            assert token3 == "ACCESS_TOKEN_ABC123"
            assert mock_post.call_count == 2

    def test_oauth_missing_credentials_raises_auth_error(self):
        """Empty credentials produce a descriptive PayPalAuthError without network call."""
        service = PayPalService(client_id="", client_secret="")
        with pytest.raises(PayPalAuthError) as exc_info:
            service.get_access_token()
        assert "PayPal credentials are not configured" in str(exc_info.value)

    def test_oauth_timeout_raises_connection_error(self):
        """Network timeout maps to PayPalConnectionError."""
        service = PayPalService(client_id="cid", client_secret="secret")
        with patch("httpx.Client.post", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(PayPalConnectionError) as exc_info:
                service.get_access_token()
            assert exc_info.value.status_code == 504

    def test_oauth_failure_raises_auth_error(self):
        """Non-200 OAuth response maps to PayPalAuthError with status 502."""
        service = PayPalService(client_id="cid", client_secret="bad_secret")
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error": "invalid_client", "error_description": "Client Authentication failed"}

        with patch("httpx.Client.post", return_value=mock_resp):
            with pytest.raises(PayPalAuthError) as exc_info:
                service.get_access_token()
            assert exc_info.value.status_code == 502
            assert "Client Authentication failed" in str(exc_info.value)

    def test_create_order_success_and_approval_url_extraction(self):
        """create_order parses returned order ID and approval link correctly."""
        service = PayPalService(client_id="cid", client_secret="secret")

        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {"access_token": "TOK", "expires_in": 3600}

        mock_order_resp = MagicMock()
        mock_order_resp.status_code = 201
        mock_order_resp.json.return_value = {
            "id": "ORDER-999",
            "status": "CREATED",
            "links": [
                {"href": "https://api-m.sandbox.paypal.com/v2/checkout/orders/ORDER-999", "rel": "self"},
                {"href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-999", "rel": "approve"},
            ],
        }

        with patch("httpx.Client.post", side_effect=[mock_token_resp, mock_order_resp]):
            result = service.create_order(
                amount=Decimal("25.50"),
                currency="USD",
                reference_id="payment_1",
                idempotency_key="idemp_1",
            )
            assert result["id"] == "ORDER-999"
            assert result["status"] == "CREATED"
            assert result["approval_url"] == "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-999"

    def test_create_order_idempotency_header(self):
        """Idempotency key is forwarded as PayPal-Request-Id header."""
        service = PayPalService(client_id="cid", client_secret="secret")
        service._access_token = "VALID_TOKEN"
        service._token_expires_at = time.time() + 3600

        mock_order_resp = MagicMock()
        mock_order_resp.status_code = 201
        mock_order_resp.json.return_value = {"id": "ORDER-1", "links": []}

        with patch("httpx.Client.post", return_value=mock_order_resp) as mock_post:
            service.create_order(
                amount=Decimal("10.00"),
                currency="USD",
                idempotency_key="stable_key_123",
            )
            _, kwargs = mock_post.call_args
            assert kwargs["headers"].get("PayPal-Request-Id") == "stable_key_123"

    def test_create_order_invalid_amount_precision_rejected(self):
        """Amounts with > 2 decimal places are rejected without silent rounding."""
        service = PayPalService(client_id="cid", client_secret="secret")
        service._access_token = "TOK"
        service._token_expires_at = time.time() + 3600

        with pytest.raises(PayPalOrderError) as exc_info:
            service.create_order(amount=Decimal("10.005"), currency="USD")
        assert "exceeds maximum supported precision" in str(exc_info.value)

    def test_create_order_invalid_currency_rejected(self):
        """Non 3-letter currency codes are rejected."""
        service = PayPalService(client_id="cid", client_secret="secret")
        service._access_token = "TOK"
        service._token_expires_at = time.time() + 3600

        with pytest.raises(PayPalOrderError) as exc_info:
            service.create_order(amount=Decimal("10.00"), currency="US_DOLLAR")
        assert "3-letter ISO code" in str(exc_info.value)

    def test_capture_order_success(self):
        """capture_order traverses response structure and extracts capture details."""
        service = PayPalService(client_id="cid", client_secret="secret")
        service._access_token = "TOK"
        service._token_expires_at = time.time() + 3600

        mock_capture_resp = MagicMock()
        mock_capture_resp.status_code = 201
        mock_capture_resp.json.return_value = {
            "id": "ORDER-999",
            "status": "COMPLETED",
            "purchase_units": [
                {
                    "payments": {
                        "captures": [
                            {
                                "id": "CAPTURE-777",
                                "status": "COMPLETED",
                                "amount": {"currency_code": "USD", "value": "10.80"},
                            }
                        ]
                    }
                }
            ],
        }

        with patch("httpx.Client.post", return_value=mock_capture_resp):
            result = service.capture_order(order_id="ORDER-999", idempotency_key="cap_key_1")
            assert result["order_id"] == "ORDER-999"
            assert result["capture_id"] == "CAPTURE-777"
            assert result["status"] == "COMPLETED"
            assert result["captured_amount"] == "10.80"
            assert result["captured_currency"] == "USD"

    def test_capture_order_missing_captures_raises_capture_error(self):
        """Response with missing captures array raises PayPalCaptureError."""
        service = PayPalService(client_id="cid", client_secret="secret")
        service._access_token = "TOK"
        service._token_expires_at = time.time() + 3600

        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"id": "ORDER-1", "status": "COMPLETED", "purchase_units": []}

        with patch("httpx.Client.post", return_value=mock_resp):
            with pytest.raises(PayPalCaptureError) as exc_info:
                service.capture_order(order_id="ORDER-1")
            assert "No capture records found" in str(exc_info.value)


# ===========================================================================
# 2. API Integration Tests for Payments Endpoints
# ===========================================================================

class TestPaymentsAPIIntegration:
    """Integration tests for /api/payments endpoints with mock PayPal responses."""

    def test_get_payment(self, client):
        payment_id = _create_payment_setup(client)
        response = client.get(f"/api/payments/{payment_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert Decimal(str(data["amount"])) == Decimal("10.80")
        assert data["currency"] == "USD"

    def test_get_payment_not_found(self, client):
        response = client.get("/api/payments/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_create_order_success_marks_order_created_and_returns_approval_url(self, client, mock_paypal_service):
        """Order creation succeeds, transitions status to order_created, and returns approval_url."""
        payment_id = _create_payment_setup(client)

        mock_paypal_service.create_order.return_value = {
            "id": "PAYPAL-ORDER-12345",
            "status": "CREATED",
            "approval_url": "https://www.sandbox.paypal.com/checkoutnow?token=PAYPAL-ORDER-12345",
            "links": [],
        }

        response = client.post(f"/api/payments/{payment_id}/create-order", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "order_created"
        assert data["paypal_order_id"] == "PAYPAL-ORDER-12345"
        assert data["approval_url"] == "https://www.sandbox.paypal.com/checkoutnow?token=PAYPAL-ORDER-12345"

        # Verify stable idempotency key was passed
        call_kwargs = mock_paypal_service.create_order.call_args.kwargs
        assert call_kwargs["idempotency_key"] == f"order_{payment_id}"

    def test_create_order_duplicate_blocked_with_409(self, client, mock_paypal_service):
        """Cannot create a second PayPal order for an existing order_created payment."""
        payment_id = _create_payment_setup(client)

        mock_paypal_service.create_order.return_value = {
            "id": "ORDER-ABC",
            "status": "CREATED",
            "approval_url": "https://sandbox.paypal.com",
        }

        # 1st call succeeds
        resp1 = client.post(f"/api/payments/{payment_id}/create-order", json={})
        assert resp1.status_code == 200

        # 2nd call rejected with 409 Conflict
        resp2 = client.post(f"/api/payments/{payment_id}/create-order", json={})
        assert resp2.status_code == 409
        assert "order_created" in resp2.json()["detail"].lower()

    def test_create_order_blocked_when_receipt_not_completed(self, client, db_session):
        """Payment creation is blocked with 400 if associated receipt is review_required."""
        payment_id = _create_payment_setup(client)
        payment = db_session.get(Payment, payment_id)
        receipt = payment.expense.receipt
        receipt.extraction_status = ExtractionStatus.REVIEW_REQUIRED
        db_session.commit()

        response = client.post(f"/api/payments/{payment_id}/create-order", json={})
        assert response.status_code == 400
        assert "receipt extraction is not completed" in response.json()["detail"].lower()

    def test_create_order_unauthorized_user_forbidden(self, client, db_session):
        """User B cannot create an order for User A's payment (403 Forbidden)."""
        payment_id = _create_payment_setup(client)

        # Create User B and client
        _, client_b, _ = create_user_and_client(db_session, email="intruder@example.com")

        response = client_b.post(f"/api/payments/{payment_id}/create-order", json={})
        assert response.status_code == 403
        assert "only manage or pay your own share" in response.json()["detail"].lower()

    def test_create_order_paypal_failure_sanitized_502(self, client, mock_paypal_service):
        """PayPal API failure returns 502 with sanitized message, not leaking credentials."""
        payment_id = _create_payment_setup(client)

        mock_paypal_service.create_order.side_effect = PayPalAuthError("Raw credential token error: secret_xyz")

        response = client.post(f"/api/payments/{payment_id}/create-order", json={})
        assert response.status_code == 502
        # Sanitized user-facing message, no raw secrets leaked
        assert "secret_xyz" not in response.text
        assert "PayPal authentication failed" in response.json()["detail"]

    def test_capture_success_marks_captured_and_persists_capture_id(self, client, db_session, mock_paypal_service):
        """Successful capture transitions payment to captured and persists capture ID."""
        payment_id = _create_payment_setup(client)

        # 1. Setup payment in ORDER_CREATED state
        payment = db_session.get(Payment, payment_id)
        payment.status = PaymentStatus.ORDER_CREATED
        payment.paypal_order_id = "PAYPAL-ORDER-VALID-1"
        db_session.commit()

        mock_paypal_service.capture_order.return_value = {
            "order_id": "PAYPAL-ORDER-VALID-1",
            "capture_id": "CAPTURE-SUCCESS-999",
            "status": "COMPLETED",
            "captured_amount": "10.80",
            "captured_currency": "USD",
        }

        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "PAYPAL-ORDER-VALID-1"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "captured"
        assert data["paypal_capture_id"] == "CAPTURE-SUCCESS-999"

        # Check DB persistence
        db_session.refresh(payment)
        assert payment.status == PaymentStatus.CAPTURED
        assert payment.paypal_capture_id == "CAPTURE-SUCCESS-999"

    def test_capture_duplicate_blocked_with_409(self, client, db_session):
        """Duplicate capture on an already captured payment returns 409 Conflict."""
        payment_id = _create_payment_setup(client)
        payment = db_session.get(Payment, payment_id)
        payment.status = PaymentStatus.CAPTURED
        payment.paypal_order_id = "PAYPAL-ORDER-1"
        payment.paypal_capture_id = "CAPTURE-1"
        db_session.commit()

        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "PAYPAL-ORDER-1"},
        )
        assert response.status_code == 409
        assert "already captured" in response.json()["detail"].lower()

    def test_capture_status_not_order_created_blocked_with_409(self, client):
        """Cannot capture a payment still in pending state."""
        payment_id = _create_payment_setup(client)
        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORDER-X"},
        )
        assert response.status_code == 409
        assert "order_created" in response.json()["detail"].lower()

    def test_capture_mismatched_order_id_rejected_with_400(self, client, db_session):
        """Cross-order capture request with mismatched order ID is rejected with 400."""
        payment_id = _create_payment_setup(client)
        payment = db_session.get(Payment, payment_id)
        payment.status = PaymentStatus.ORDER_CREATED
        payment.paypal_order_id = "EXPECTED-ORDER-1"
        db_session.commit()

        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "WRONG-ORDER-999"},
        )
        assert response.status_code == 400
        assert "does not match" in response.json()["detail"].lower()

    def test_capture_unauthorized_user_rejected_with_403(self, client, db_session):
        """User B cannot capture User A's payment (403 Forbidden)."""
        payment_id = _create_payment_setup(client)
        payment = db_session.get(Payment, payment_id)
        payment.status = PaymentStatus.ORDER_CREATED
        payment.paypal_order_id = "ORDER-1"
        db_session.commit()

        _, client_b, _ = create_user_and_client(db_session, email="attacker@example.com")
        response = client_b.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORDER-1"},
        )
        assert response.status_code == 403

    def test_capture_non_completed_status_marks_failed_never_captured(self, client, db_session, mock_paypal_service):
        """Non-COMPLETED PayPal capture status marks payment as FAILED and returns 400."""
        payment_id = _create_payment_setup(client)
        payment = db_session.get(Payment, payment_id)
        payment.status = PaymentStatus.ORDER_CREATED
        payment.paypal_order_id = "ORDER-PENDING"
        db_session.commit()

        mock_paypal_service.capture_order.return_value = {
            "order_id": "ORDER-PENDING",
            "capture_id": "CAP-1",
            "status": "PENDING",  # Not COMPLETED
            "captured_amount": "10.80",
            "captured_currency": "USD",
        }

        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORDER-PENDING"},
        )
        assert response.status_code == 400
        assert "not completed" in response.json()["detail"].lower()

        db_session.refresh(payment)
        assert payment.status == PaymentStatus.FAILED
        assert payment.paypal_capture_id is None

    def test_capture_missing_capture_id_marks_failed_never_captured(self, client, db_session, mock_paypal_service):
        """Missing capture ID marks payment as FAILED and returns 400."""
        payment_id = _create_payment_setup(client)
        payment = db_session.get(Payment, payment_id)
        payment.status = PaymentStatus.ORDER_CREATED
        payment.paypal_order_id = "ORDER-NO-ID"
        db_session.commit()

        mock_paypal_service.capture_order.return_value = {
            "order_id": "ORDER-NO-ID",
            "capture_id": None,  # Missing
            "status": "COMPLETED",
            "captured_amount": "10.80",
            "captured_currency": "USD",
        }

        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORDER-NO-ID"},
        )
        assert response.status_code == 400
        db_session.refresh(payment)
        assert payment.status == PaymentStatus.FAILED

    def test_capture_amount_mismatch_marks_failed_never_captured(self, client, db_session, mock_paypal_service):
        """Captured amount differing from database amount marks payment as FAILED."""
        payment_id = _create_payment_setup(client)
        payment = db_session.get(Payment, payment_id)
        payment.status = PaymentStatus.ORDER_CREATED
        payment.paypal_order_id = "ORDER-MISMATCH"
        db_session.commit()

        mock_paypal_service.capture_order.return_value = {
            "order_id": "ORDER-MISMATCH",
            "capture_id": "CAP-MISMATCH",
            "status": "COMPLETED",
            "captured_amount": "999.00",  # DB expects 10.80
            "captured_currency": "USD",
        }

        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORDER-MISMATCH"},
        )
        assert response.status_code == 400
        assert "amount does not match" in response.json()["detail"].lower()

        db_session.refresh(payment)
        assert payment.status == PaymentStatus.FAILED

    def test_capture_currency_mismatch_marks_failed_never_captured(self, client, db_session, mock_paypal_service):
        """Captured currency differing from database currency marks payment as FAILED."""
        payment_id = _create_payment_setup(client)
        payment = db_session.get(Payment, payment_id)
        payment.status = PaymentStatus.ORDER_CREATED
        payment.paypal_order_id = "ORDER-CURR-MISMATCH"
        db_session.commit()

        mock_paypal_service.capture_order.return_value = {
            "order_id": "ORDER-CURR-MISMATCH",
            "capture_id": "CAP-CURR",
            "status": "COMPLETED",
            "captured_amount": "10.80",
            "captured_currency": "EUR",  # DB expects USD
        }

        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORDER-CURR-MISMATCH"},
        )
        assert response.status_code == 400
        assert "currency does not match" in response.json()["detail"].lower()

        db_session.refresh(payment)
        assert payment.status == PaymentStatus.FAILED

    def test_capture_blocked_when_receipt_not_completed(self, client, db_session, mock_paypal_service):
        """Capture is blocked with 400 if receipt status was reverted to review_required."""
        payment_id = _create_payment_setup(client)
        payment = db_session.get(Payment, payment_id)
        payment.status = PaymentStatus.ORDER_CREATED
        payment.paypal_order_id = "ORDER-RECEIPT-REV"
        receipt = payment.expense.receipt
        receipt.extraction_status = ExtractionStatus.REVIEW_REQUIRED
        db_session.commit()

        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORDER-RECEIPT-REV"},
        )
        assert response.status_code == 400
        assert "receipt extraction is not completed" in response.json()["detail"].lower()

    def test_capture_paypal_error_marks_payment_failed_never_captured(self, client, db_session, mock_paypal_service):
        """PayPal API error during capture sets payment to FAILED and returns 502."""
        payment_id = _create_payment_setup(client)
        payment = db_session.get(Payment, payment_id)
        payment.status = PaymentStatus.ORDER_CREATED
        payment.paypal_order_id = "ORDER-ERR"
        db_session.commit()

        mock_paypal_service.capture_order.side_effect = PayPalCaptureError("Card declined")

        response = client.post(
            f"/api/payments/{payment_id}/capture",
            json={"paypal_order_id": "ORDER-ERR"},
        )
        assert response.status_code == 502
        assert "payment capture failed" in response.json()["detail"].lower()

        db_session.refresh(payment)
        assert payment.status == PaymentStatus.FAILED
