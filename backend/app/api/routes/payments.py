"""Payment endpoints — PayPal Sandbox integration.

Secured with JWT authentication, payer-only authorization, receipt extraction
completion pre-flight guards, server-side capture verification, and idempotency.
"""

from decimal import Decimal
import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import ExtractionStatus, Payment, PaymentStatus, User
from app.schemas.schemas import (
    PaymentCaptureRequest,
    PaymentCreateOrderRequest,
    PaymentResponse,
)
from app.services.authorization import require_payment_access
from app.services.paypal_service import (
    PayPalAuthError,
    PayPalCaptureError,
    PayPalConnectionError,
    PayPalOrderError,
    PayPalService,
    paypal_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["Payments"])


def get_paypal_service() -> PayPalService:
    """FastAPI dependency to inject PayPalService (overridable in tests)."""
    return paypal_service


@router.post(
    "/{payment_id}/create-order",
    response_model=PaymentResponse,
    summary="Create a PayPal order for a payment",
)
def create_paypal_order(
    payment_id: uuid.UUID,
    body: PaymentCreateOrderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: PayPalService = Depends(get_paypal_service),
):
    """Create a PayPal checkout order for an authorized pending payment.

    - Payer authorization enforced: only the designated paying member may initiate.
    - Status must be PENDING; blocks duplicate order creation.
    - Validates associated receipt is fully extracted (COMPLETED).
    - Uses server-side amount and currency (never trusts client input).
    - Disallows invalid amount precision (no silent rounding).
    - Sets stable PayPal-Request-Id for idempotency.
    - Stores returned PayPal order ID and transitions status to ORDER_CREATED.
    """
    payment = require_payment_access(db, payment_id, current_user, require_payer=True)

    if payment.status != PaymentStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Payment is in '{payment.status.value}' state. Can only create order for 'pending' payments.",
        )

    if payment.paypal_order_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A PayPal order has already been created for this payment.",
        )

    # Receipt extraction eligibility check: receipt must be COMPLETED
    if payment.expense and payment.expense.receipt_id:
        receipt = payment.expense.receipt
        if not receipt or receipt.extraction_status != ExtractionStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Cannot create PayPal order: the associated receipt extraction is not completed. "
                    f"Current status: {receipt.extraction_status.value if receipt else 'not found'}."
                ),
            )

    # Validate amount precision and currency strictly (no silent rounding)
    if payment.amount <= Decimal("0"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment amount must be greater than zero.",
        )
    if payment.amount.quantize(Decimal("0.01")) != payment.amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment amount precision is invalid (maximum 2 decimal places).",
        )

    currency = payment.currency.strip().upper()
    if not re.match(r"^[A-Z]{3}$", currency):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid currency code '{payment.currency}'. Must be a 3-letter ISO code.",
        )

    # Stable idempotency key for this payment
    idempotency_key = f"order_{payment.id}"

    try:
        order_result = service.create_order(
            amount=payment.amount,
            currency=currency,
            reference_id=str(payment.id),
            description=f"SplitMate settlement for expense {payment.expense_id}",
            return_url=body.return_url,
            cancel_url=body.cancel_url,
            idempotency_key=idempotency_key,
        )
    except PayPalAuthError as exc:
        logger.error("PayPal auth failed during order creation for payment %s: %s", payment_id, exc.message)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal authentication failed. Please contact support.",
        ) from exc
    except PayPalConnectionError as exc:
        logger.error("PayPal connection timeout during order creation for payment %s: %s", payment_id, exc.message)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="PayPal service connection timed out. Please try again.",
        ) from exc
    except PayPalOrderError as exc:
        logger.error("PayPal order creation rejected for payment %s: %s", payment_id, exc.message)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal order creation failed. Please try again.",
        ) from exc

    payment.paypal_order_id = order_result["id"]
    payment.status = PaymentStatus.ORDER_CREATED
    db.commit()
    db.refresh(payment)

    # Attach approval_url transiently for response serialization
    payment.approval_url = order_result.get("approval_url")
    return payment


@router.post(
    "/{payment_id}/capture",
    response_model=PaymentResponse,
    summary="Capture a PayPal payment",
)
def capture_payment(
    payment_id: uuid.UUID,
    body: PaymentCaptureRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    service: PayPalService = Depends(get_paypal_service),
):
    """Capture an authorized PayPal payment.

    - Payer authorization enforced: only the designated paying member may capture.
    - Row-level lock used to prevent concurrent double-capture race conditions.
    - Validates status is ORDER_CREATED and order ID matches payment record.
    - Validates receipt is still COMPLETED (if linked).
    - Sends stable PayPal-Request-Id for safe capture retry.
    - Server-side verification: verifies PayPal capture status is COMPLETED.
    - Server-side verification: asserts captured amount matches expected DB amount.
    - Server-side verification: asserts captured currency matches expected DB currency.
    - Updates payment status to CAPTURED on success, or FAILED on rejection.
    """
    payment = require_payment_access(db, payment_id, current_user, require_payer=True)

    if payment.status == PaymentStatus.CAPTURED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment already captured.")

    if payment.status != PaymentStatus.ORDER_CREATED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Payment is in '{payment.status.value}' state. Can only capture 'order_created' payments.",
        )

    # Prevent cross-order or mismatched captures
    if payment.paypal_order_id and payment.paypal_order_id != body.paypal_order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PayPal order ID does not match the payment record.",
        )

    # Receipt extraction eligibility check: receipt must be COMPLETED
    if payment.expense and payment.expense.receipt_id:
        receipt = payment.expense.receipt
        if not receipt or receipt.extraction_status != ExtractionStatus.COMPLETED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Cannot capture PayPal payment: the associated receipt extraction is not completed. "
                    f"Current status: {receipt.extraction_status.value if receipt else 'not found'}."
                ),
            )

    # Pessimistic locking (with SQLite fallback) to protect against concurrent captures
    try:
        locked_payment = (
            db.query(Payment)
            .filter(Payment.id == payment_id)
            .with_for_update()
            .first()
        )
        if locked_payment:
            payment = locked_payment
    except OperationalError as exc:
        exc_str = str(exc).lower()
        if "cannot use" in exc_str or "for update" in exc_str:
            logger.debug("SELECT FOR UPDATE not supported (SQLite); using unguarded read.")
        else:
            raise

    # Re-verify state under lock
    if payment.status == PaymentStatus.CAPTURED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment already captured.")
    if payment.status != PaymentStatus.ORDER_CREATED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Payment is in '{payment.status.value}' state. Can only capture 'order_created' payments.",
        )

    # Stable idempotency key for capture retries
    idempotency_key = f"capture_{payment.id}_{body.paypal_order_id}"

    try:
        capture_result = service.capture_order(
            order_id=body.paypal_order_id,
            idempotency_key=idempotency_key,
        )
    except PayPalAuthError as exc:
        logger.error("PayPal auth failure during capture for payment %s: %s", payment_id, exc.message)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal authentication failed. Please contact support.",
        ) from exc
    except PayPalConnectionError as exc:
        logger.error("PayPal timeout/network error during capture for payment %s: %s", payment_id, exc.message)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="PayPal service timed out during capture. Please retry.",
        ) from exc
    except PayPalCaptureError as exc:
        logger.error("PayPal capture failed for payment %s: %s", payment_id, exc.message)
        payment.status = PaymentStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="PayPal payment capture failed.",
        ) from exc

    # Server-Side Verification: Ensure capture status is COMPLETED
    capture_status = (capture_result.get("status") or "").upper()
    if capture_status != "COMPLETED":
        logger.error("PayPal capture status for payment %s is '%s', not COMPLETED", payment_id, capture_status)
        payment.status = PaymentStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PayPal capture status '{capture_status}' is not COMPLETED.",
        )

    # Server-Side Verification: Ensure capture ID is present
    capture_id = capture_result.get("capture_id")
    if not capture_id:
        logger.error("PayPal capture response for payment %s missing capture ID", payment_id)
        payment.status = PaymentStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PayPal capture response missing capture ID.",
        )

    # Server-Side Verification: Ensure captured amount matches expected DB amount
    try:
        captured_amount_dec = Decimal(str(capture_result.get("captured_amount")))
        if captured_amount_dec != payment.amount:
            logger.error("Captured amount (%s) differs from payment amount (%s)", captured_amount_dec, payment.amount)
            payment.status = PaymentStatus.FAILED
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Captured amount does not match expected payment amount.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        payment.status = PaymentStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or missing captured amount in PayPal response.",
        ) from exc

    # Server-Side Verification: Ensure captured currency matches expected DB currency
    captured_currency = (capture_result.get("captured_currency") or "").strip().upper()
    if captured_currency != payment.currency.strip().upper():
        logger.error("Captured currency (%s) differs from payment currency (%s)", captured_currency, payment.currency)
        payment.status = PaymentStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Captured currency does not match expected payment currency.",
        )

    # All server-side checks passed: mark CAPTURED
    payment.paypal_capture_id = capture_id
    payment.status = PaymentStatus.CAPTURED
    db.commit()
    db.refresh(payment)
    return payment


@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
    summary="Get payment status",
)
def get_payment(
    payment_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payment = require_payment_access(db, payment_id, current_user, require_payer=False)
    return payment
