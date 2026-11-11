"""PayPal Sandbox API integration service using PayPal Orders API v2.

Handles OAuth 2.0 client credentials authentication, order creation,
and server-side payment capture using the official PayPal REST v2 endpoints.
"""

from decimal import Decimal
import logging
import time
from typing import Any
import uuid

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom PayPal Exceptions
# ---------------------------------------------------------------------------

class PayPalError(Exception):
    """Base exception for PayPal operations."""
    def __init__(self, message: str, status_code: int = 502, details: Any = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details


class PayPalAuthError(PayPalError):
    """Raised when OAuth 2.0 authentication fails."""
    def __init__(self, message: str = "PayPal authentication failed.", details: Any = None):
        super().__init__(message=message, status_code=502, details=details)


class PayPalOrderError(PayPalError):
    """Raised when PayPal order creation fails."""
    def __init__(
        self,
        message: str = "PayPal order creation failed.",
        status_code: int = 502,
        details: Any = None,
        issue: str | None = None,
    ):
        super().__init__(message=message, status_code=status_code, details=details)
        self.issue = issue


class PayPalCaptureError(PayPalError):
    """Raised when PayPal payment capture fails."""
    def __init__(
        self,
        message: str = "PayPal payment capture failed.",
        status_code: int = 502,
        details: Any = None,
        issue: str | None = None,
    ):
        super().__init__(message=message, status_code=status_code, details=details)
        self.issue = issue


class PayPalConnectionError(PayPalError):
    """Raised when PayPal network or timeout error occurs."""
    def __init__(self, message: str = "PayPal service connection error.", details: Any = None):
        super().__init__(message=message, status_code=504, details=details)


# ---------------------------------------------------------------------------
# PayPal Service Class
# ---------------------------------------------------------------------------

class PayPalService:
    """Encapsulates PayPal Orders v2 API interactions."""

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ):
        # Use explicit None check to distinguish "" from None
        self.client_id = client_id if client_id is not None else settings.PAYPAL_CLIENT_ID
        self.client_secret = client_secret if client_secret is not None else settings.PAYPAL_CLIENT_SECRET
        self.base_url = (base_url or settings.PAYPAL_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.PAYPAL_TIMEOUT_SECONDS

        # Token caching state
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._mock_mode: bool = False
        self._mock_orders: dict[str, dict[str, Any]] = {}

    @property
    def mock_mode(self) -> bool:
        """Check if service is explicitly forced into mock mode."""
        return self._mock_mode

    @mock_mode.setter
    def mock_mode(self, value: bool) -> None:
        """Explicitly enable or disable mock mode."""
        self._mock_mode = bool(value)

    @property
    def is_configured(self) -> bool:
        """Returns True if live/sandbox credentials are provided and non-dummy,
        unless mock mode is explicitly forced.
        """
        if self._mock_mode:
            return False
        if getattr(settings, "PAYPAL_MOCK_MODE", False):
            return False
        return bool(
            self.client_id
            and self.client_secret
            and not self.client_id.startswith("mock")
            and self.client_id.strip() != ""
        )

    def get_access_token(self, force_refresh: bool = False) -> str:
        """Obtain or return a cached PayPal OAuth 2.0 access token.

        Uses client_credentials grant type and basic authentication.
        Caches the token in-memory until 60 seconds before expiration.
        """
        if self._mock_mode:
            return "mock_sandbox_access_token"

        now = time.time()
        if not force_refresh and self._access_token and now < self._token_expires_at:
            return self._access_token

        # Check credentials before making network call
        if not self.client_id or not self.client_secret or not self.client_id.strip() or not self.client_secret.strip():
            raise PayPalAuthError(
                message="PayPal credentials are not configured. Set PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET."
            )

        token_url = f"{self.base_url}/v1/oauth2/token"
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en_US",
        }
        data = {"grant_type": "client_credentials"}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    token_url,
                    data=data,
                    headers=headers,
                    auth=(self.client_id, self.client_secret),
                )
        except httpx.TimeoutException as exc:
            logger.error("PayPal OAuth token request timed out.")
            raise PayPalConnectionError("PayPal authentication timed out.", details=str(exc)) from exc
        except httpx.RequestError as exc:
            logger.error("Network error during PayPal OAuth token request: %s", type(exc).__name__)
            raise PayPalConnectionError("Failed to reach PayPal authentication service.", details=str(exc)) from exc

        if response.status_code != 200:
            error_data = None
            try:
                error_data = response.json()
            except Exception:
                pass
            logger.error("PayPal OAuth failed with status code %s", response.status_code)
            error_desc = error_data.get("error_description") if isinstance(error_data, dict) else "Authentication rejected."
            raise PayPalAuthError(
                message=f"PayPal authentication failed: {error_desc}",
                details=error_data,
            )

        try:
            token_data = response.json()
            access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
        except (KeyError, ValueError, TypeError) as exc:
            logger.error("Malformed response from PayPal OAuth endpoint.")
            raise PayPalAuthError("Malformed response received from PayPal token service.", details=str(exc)) from exc

        self._access_token = access_token
        # Cache token with 60s safety buffer
        self._token_expires_at = now + float(expires_in) - 60.0
        return self._access_token

    def create_order(
        self,
        amount: Decimal | str,
        currency: str = "USD",
        reference_id: str | None = None,
        description: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Create a PayPal checkout order with intent CAPTURE.

        Args:
            amount: Server-side decimal amount (never client-supplied).
            currency: 3-letter currency code (e.g. USD).
            reference_id: Internal payment ID for reference.
            description: Human-readable note for purchase unit.
            return_url: Optional approval return URL.
            cancel_url: Optional cancel URL.
            idempotency_key: Unique key for PayPal-Request-Id header.

        Returns:
            Dict containing order id, status, approval_url, and links.
        """
        if self._mock_mode:
            ref_slug = reference_id[:8] if reference_id else uuid.uuid4().hex[:8]
            order_id = f"MOCK-ORD-{ref_slug.upper()}-{int(time.time())}"
            approval_url = f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}"
            self._mock_orders[order_id] = {
                "id": order_id,
                "amount": amount,
                "currency": currency,
                "status": "CREATED",
                "reference_id": reference_id,
            }
            return {
                "id": order_id,
                "status": "CREATED",
                "approval_url": approval_url,
                "links": [{"rel": "approve", "href": approval_url}],
                "raw_response": {"id": order_id, "status": "CREATED"},
                "mock": True,
            }

        token = self.get_access_token()

        try:
            dec_amount = Decimal(str(amount))
            if dec_amount <= Decimal("0"):
                raise ValueError("Amount must be greater than zero.")
            formatted_amount = f"{dec_amount:.2f}"
        except Exception as exc:
            raise PayPalOrderError(f"Invalid payment amount: {amount}") from exc

        orders_url = f"{self.base_url}/v2/checkout/orders"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        if idempotency_key:
            headers["PayPal-Request-Id"] = idempotency_key

        purchase_unit = {
            "reference_id": reference_id or "default",
            "description": (description or "SplitMate Expense Settlement")[:127],
            "amount": {
                "currency_code": currency.upper(),
                "value": formatted_amount,
            },
        }

        payload: dict[str, Any] = {
            "intent": "CAPTURE",
            "purchase_units": [purchase_unit],
            "application_context": {
                "brand_name": "SplitMate",
                "landing_page": "NO_PREFERENCE",
                "user_action": "PAY_NOW",
                "return_url": return_url or "https://splitmate.local/payment/return",
                "cancel_url": cancel_url or "https://splitmate.local/payment/cancel",
            },
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(orders_url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("PayPal Create Order request timed out.")
            raise PayPalConnectionError("PayPal order creation timed out.", details=str(exc)) from exc
        except httpx.RequestError as exc:
            logger.error("Network error during PayPal Create Order: %s", type(exc).__name__)
            raise PayPalConnectionError("Failed to reach PayPal order service.", details=str(exc)) from exc

        if response.status_code not in (200, 201):
            error_data = None
            issue = None
            try:
                error_data = response.json()
            except Exception:
                pass
            logger.error("PayPal create order failed with status %s", response.status_code)
            message = "PayPal order creation failed."
            if isinstance(error_data, dict):
                msg = error_data.get("message")
                details = error_data.get("details")
                if details and isinstance(details, list) and len(details) > 0:
                    issue = details[0].get("issue")
                    desc = details[0].get("description") or issue
                    message = f"{msg}: {desc}" if msg and desc else (msg or desc or message)
                elif msg:
                    message = msg

            raise PayPalOrderError(
                message=message,
                status_code=response.status_code,
                details=error_data,
                issue=issue,
            )

        try:
            data = response.json()
            order_id = data["id"]
            order_status = data.get("status", "CREATED")
            links = data.get("links", [])
        except (KeyError, ValueError, TypeError) as exc:
            logger.error("Malformed response from PayPal Create Order.")
            raise PayPalOrderError("Malformed response from PayPal order service.", details=str(exc)) from exc

        approval_url = None
        for link in links:
            if link.get("rel") in ("approve", "approval_url"):
                approval_url = link.get("href")
                break

        return {
            "id": order_id,
            "status": order_status,
            "approval_url": approval_url,
            "links": links,
            "raw_response": data,
        }

    def _parse_order_capture(self, order_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """Extract and validate capture record from PayPal response payload."""
        overall_status = data.get("status")

        purchase_units = data.get("purchase_units", [])
        captures = []
        if purchase_units and isinstance(purchase_units, list):
            payments = purchase_units[0].get("payments", {})
            captures = payments.get("captures", [])

        if not captures:
            raise PayPalCaptureError(
                message="No capture records found in PayPal response.",
                details=data,
            )

        primary_capture = captures[0]
        capture_id = primary_capture.get("id")
        capture_status = primary_capture.get("status")
        amount_info = primary_capture.get("amount", {})
        captured_amount = amount_info.get("value")
        captured_currency = amount_info.get("currency_code")

        if not capture_id:
            raise PayPalCaptureError(
                message="PayPal capture response missing capture ID.",
                details=data,
            )

        return {
            "order_id": order_id,
            "capture_id": capture_id,
            "status": capture_status or overall_status,
            "overall_status": overall_status,
            "captured_amount": captured_amount,
            "captured_currency": captured_currency,
            "raw_response": data,
        }

    def capture_order(
        self,
        order_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Capture an approved PayPal order.

        Includes automatic reconciliation if PayPal returns ORDER_ALREADY_CAPTURED
        (e.g., following a network timeout on a previous attempt).

        Args:
            order_id: The PayPal order ID.
            idempotency_key: Unique key for PayPal-Request-Id header.

        Returns:
            Dict containing capture_id, status, captured_amount, captured_currency, raw_response.
        """
        if self._mock_mode:
            order_info = self._mock_orders.get(order_id, {})
            order_suffix = order_id[-8:] if len(order_id) >= 8 else uuid.uuid4().hex[:8]
            capture_id = f"MOCK-CAP-{order_suffix.upper()}"
            amount = order_info.get("amount", Decimal("25.00"))
            currency = order_info.get("currency", "USD")
            order_info["status"] = "COMPLETED"
            order_info["capture_id"] = capture_id
            return {
                "order_id": order_id,
                "capture_id": capture_id,
                "status": "COMPLETED",
                "overall_status": "COMPLETED",
                "captured_amount": str(amount),
                "captured_currency": currency,
                "raw_response": {"id": capture_id, "status": "COMPLETED"},
                "mock": True,
            }

        token = self.get_access_token()

        capture_url = f"{self.base_url}/v2/checkout/orders/{order_id}/capture"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        if idempotency_key:
            headers["PayPal-Request-Id"] = idempotency_key

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(capture_url, json={}, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("PayPal Capture Order request timed out for order %s", order_id)
            raise PayPalConnectionError("PayPal payment capture timed out.", details=str(exc)) from exc
        except httpx.RequestError as exc:
            logger.error("Network error during PayPal Capture Order: %s", type(exc).__name__)
            raise PayPalConnectionError("Failed to reach PayPal capture service.", details=str(exc)) from exc

        if response.status_code not in (200, 201):
            error_data = None
            issue = None
            try:
                error_data = response.json()
            except Exception:
                pass
            logger.error("PayPal capture failed with status %s for order %s", response.status_code, order_id)

            # Check for ORDER_ALREADY_CAPTURED to reconcile idempotent retries
            is_already_captured = False
            if isinstance(error_data, dict):
                details = error_data.get("details", [])
                if isinstance(details, list):
                    for d in details:
                        if isinstance(d, dict) and d.get("issue") == "ORDER_ALREADY_CAPTURED":
                            is_already_captured = True
                            issue = "ORDER_ALREADY_CAPTURED"
                            break

            if is_already_captured:
                logger.info(
                    "Order %s was already captured on PayPal. Reconciling via order details...",
                    order_id,
                )
                try:
                    order_details = self.get_order_details(order_id)
                    return self._parse_order_capture(order_id, order_details)
                except Exception as rec_exc:
                    logger.warning("Failed automatic reconciliation for order %s: %s", order_id, rec_exc)

            message = "PayPal payment capture failed."
            if isinstance(error_data, dict):
                msg = error_data.get("message")
                details = error_data.get("details")
                if details and isinstance(details, list) and len(details) > 0:
                    issue = details[0].get("issue") or issue
                    desc = details[0].get("description") or issue
                    message = f"{msg}: {desc}" if msg and desc else (msg or desc or message)
                elif msg:
                    message = msg

            raise PayPalCaptureError(
                message=message,
                status_code=response.status_code,
                details=error_data,
                issue=issue,
            )

        try:
            data = response.json()
            return self._parse_order_capture(order_id, data)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            logger.error("Malformed capture response from PayPal: %s", exc)
            raise PayPalCaptureError(
                message="Malformed response received from PayPal capture service.",
                details=str(exc),
            ) from exc

    def get_order_details(self, order_id: str) -> dict[str, Any]:
        """Fetch details of an existing order from PayPal."""
        if self._mock_mode:
            order_info = self._mock_orders.get(order_id, {})
            return {
                "id": order_id,
                "status": order_info.get("status", "COMPLETED"),
                "purchase_units": [
                    {
                        "amount": {
                            "value": str(order_info.get("amount", Decimal("25.00"))),
                            "currency_code": order_info.get("currency", "USD"),
                        }
                    }
                ],
            }

        token = self.get_access_token()
        url = f"{self.base_url}/v2/checkout/orders/{order_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, headers=headers)
        except httpx.TimeoutException as exc:
            raise PayPalConnectionError("PayPal get order timed out.", details=str(exc)) from exc
        except httpx.RequestError as exc:
            raise PayPalConnectionError("Failed to reach PayPal order service.", details=str(exc)) from exc

        if response.status_code != 200:
            raise PayPalOrderError(
                message=f"Failed to fetch order details (status {response.status_code}).",
                status_code=response.status_code,
            )

        return response.json()


# Module-level default singleton instance
paypal_service = PayPalService()
