"""PayPal Sandbox Integration Service for SplitMate.

Handles OAuth2 authentication, Orders API v2 order creation, and server-side capture verification.
Supports automatic sandbox mock fallback when live credentials are not configured or offline.
"""

from decimal import Decimal
import logging
import time
from typing import Any
import uuid

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class PayPalService:
    """Encapsulates interaction with PayPal Developer REST APIs."""

    def __init__(self):
        self._cached_token: str | None = None
        self._token_expires_at: float = 0.0
        self._mock_mode: bool = False

    @property
    def mock_mode(self) -> bool:
        """Check if service is explicitly forced into mock mode."""
        return self._mock_mode

    @mock_mode.setter
    def mock_mode(self, value: bool) -> None:
        """Explicitly enable or disable mock mode (useful for test isolation)."""
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
            settings.PAYPAL_CLIENT_ID
            and settings.PAYPAL_CLIENT_SECRET
            and not settings.PAYPAL_CLIENT_ID.startswith("mock")
            and settings.PAYPAL_CLIENT_ID.strip() != ""
        )

    def get_access_token(self) -> str:
        """Obtain or return cached OAuth2 access token from PayPal Sandbox."""
        if not self.is_configured:
            return "mock_sandbox_access_token"

        now = time.time()
        if self._cached_token and now < self._token_expires_at:
            return self._cached_token

        token_url = f"{settings.PAYPAL_BASE_URL.rstrip('/')}/v1/oauth2/token"
        headers = {
            "Accept": "application/json",
            "Accept-Language": "en_US",
        }
        data = {"grant_type": "client_credentials"}

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    token_url,
                    auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
                    headers=headers,
                    data=data,
                )
                resp.raise_for_status()
                token_data = resp.json()

            self._cached_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            self._token_expires_at = now + expires_in - 60  # 60s buffer
            return self._cached_token
        except Exception as e:
            logger.error("Failed to authenticate with PayPal Sandbox: %s", e)
            raise RuntimeError(f"PayPal authentication failure: {e}") from e

    def create_order(
        self, amount: Decimal, currency: str = "USD", reference_id: str = ""
    ) -> dict[str, Any]:
        """Create a PayPal checkout order with backend-verified amount."""
        formatted_amount = f"{amount:.2f}"

        if not self.is_configured:
            if getattr(settings, "APP_ENV", "development") == "production":
                raise RuntimeError("PayPal service is unconfigured or unavailable in production environment.")
            ref_slug = reference_id[:8] if reference_id else uuid.uuid4().hex[:8]
            order_id = f"MOCK-ORD-{ref_slug.upper()}-{int(time.time())}"
            return {
                "id": order_id,
                "status": "CREATED",
                "mock": True,
            }

        access_token = self.get_access_token()
        orders_url = f"{settings.PAYPAL_BASE_URL.rstrip('/')}/v2/checkout/orders"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": reference_id or "splitmate_payment",
                    "description": "SplitMate Group Expense Settlement",
                    "amount": {
                        "currency_code": currency,
                        "value": formatted_amount,
                    },
                }
            ],
        }

        with httpx.Client(timeout=15.0) as client:
            resp = client.post(orders_url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()

    def capture_payment(self, order_id: str) -> dict[str, Any]:
        """Capture an approved PayPal order and verify server-side status."""
        if not self.is_configured:
            if getattr(settings, "APP_ENV", "development") == "production":
                raise RuntimeError("PayPal service is unconfigured or unavailable in production environment.")
            order_suffix = order_id[-8:] if len(order_id) >= 8 else uuid.uuid4().hex[:8]
            capture_id = f"MOCK-CAP-{order_suffix.upper()}"
            return {
                "capture_id": capture_id,
                "status": "COMPLETED",
                "mock": True,
            }

        access_token = self.get_access_token()
        capture_url = (
            f"{settings.PAYPAL_BASE_URL.rstrip('/')}/v2/checkout/orders/{order_id}/capture"
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }

        with httpx.Client(timeout=15.0) as client:
            resp = client.post(capture_url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        order_status = data.get("status")
        if order_status != "COMPLETED":
            logger.warning("PayPal capture did not complete. Status: %s", order_status)
            return {"capture_id": None, "status": order_status, "raw": data}

        capture_id = None
        try:
            purchase_units = data.get("purchase_units", [])
            if purchase_units:
                captures = (
                    purchase_units[0].get("payments", {}).get("captures", [])
                )
                if captures:
                    capture_id = captures[0].get("id")
        except Exception:
            pass

        return {
            "capture_id": capture_id or order_id,
            "status": "COMPLETED",
            "raw": data,
        }


paypal_service = PayPalService()
