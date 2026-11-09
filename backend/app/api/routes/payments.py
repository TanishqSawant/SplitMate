"""Payment endpoints — PayPal Sandbox integration. Owned and maintained by Tanay."""

from decimal import Decimal
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import Payment, PaymentStatus
from app.schemas.schemas import (
    PaymentCaptureRequest,
    PaymentCreateOrderRequest,
    PaymentDirectCaptureRequest,
    PaymentDirectCreateOrderRequest,
    PaymentResponse,
)
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


# ---------------------------------------------------------------------------
# Static Routes (Defined before /{payment_id} parameterized routes for FastAPI matching)
# ---------------------------------------------------------------------------

@router.get(
    "/history",
    response_model=list[PaymentResponse],
    summary="Get payment history",
)
def list_payments(db: Session = Depends(get_db)):
    """Return all payment transactions ordered by creation date."""
    return db.query(Payment).order_by(Payment.created_at.desc()).limit(100).all()


@router.post(
    "/paypal/create-order",
    response_model=PaymentResponse,
    summary="Create PayPal order (Frontend compatibility route)",
)
def create_paypal_order_direct(
    body: PaymentDirectCreateOrderRequest,
    db: Session = Depends(get_db),
    service: PayPalService = Depends(get_paypal_service),
):
    """Direct route supporting Dhruv's frontend calling /api/payments/paypal/create-order."""
    payment: Payment | None = None

    if body.payment_id:
        payment = db.get(Payment, body.payment_id)
    elif body.payer_id and body.expense_id:
        payment = (
            db.query(Payment)
            .filter(Payment.member_id == body.payer_id, Payment.expense_id == body.expense_id)
            .first()
        )
    elif body.payer_id:
        payment = (
            db.query(Payment)
            .filter(Payment.member_id == body.payer_id, Payment.status == PaymentStatus.PENDING)
            .order_by(Payment.created_at.desc())
            .first()
        )

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending payment record found matching the provided parameters.",
        )

    req = PaymentCreateOrderRequest()
    return create_paypal_order(payment_id=payment.id, body=req, db=db, service=service)


@router.post(
    "/paypal/capture-order",
    response_model=PaymentResponse,
    summary="Capture PayPal order (Frontend compatibility route)",
)
def capture_payment_direct(
    body: PaymentDirectCaptureRequest,
    db: Session = Depends(get_db),
    service: PayPalService = Depends(get_paypal_service),
):
    """Direct route supporting Dhruv's frontend calling /api/payments/paypal/capture-order."""
    payment: Payment | None = None

    if body.payment_id:
        payment = db.get(Payment, body.payment_id)
    else:
        payment = (
            db.query(Payment)
            .filter(Payment.paypal_order_id == body.order_id)
            .first()
        )

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Payment record for PayPal order '{body.order_id}' not found.",
        )

    req = PaymentCaptureRequest(paypal_order_id=body.order_id)
    return capture_payment(payment_id=payment.id, body=req, db=db, service=service)


# ---------------------------------------------------------------------------
# Core Primary Endpoints (Tanishq's REST Contract)
# ---------------------------------------------------------------------------

@router.post(
    "/{payment_id}/create-order",
    response_model=PaymentResponse,
    summary="Create a PayPal order for a payment (Tanay implements)",
)
def create_paypal_order(
    payment_id: uuid.UUID,
    body: PaymentCreateOrderRequest,
    db: Session = Depends(get_db),
    service: PayPalService = Depends(get_paypal_service),
):
    """Create a PayPal checkout order for a verified server-side pending payment.

    - Verifies payment existence in database.
    - Ensures status is PENDING and no existing order is attached.
    - Uses server-side amount and currency (never trusts client amount).
    - Calls PayPal Orders API v2 (intent=CAPTURE).
    - Records returned PayPal order ID and marks payment as ORDER_CREATED.
    """
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found.")

    if payment.paypal_order_id or payment.status != PaymentStatus.PENDING:
        detail_msg = (
            "A PayPal order has already been created for this payment."
            if payment.paypal_order_id
            else f"Payment is in '{payment.status.value}' state. Can only create order for 'pending' payments."
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail_msg,
        )

    # Call PayPal Orders API v2
    try:
        order_data = service.create_order(
            amount=payment.amount,
            currency=payment.currency,
            reference_id=str(payment.id),
            description=f"SplitMate expense split payment {payment.id}",
            return_url=body.return_url,
            cancel_url=body.cancel_url,
            idempotency_key=f"order_{payment.id}",
        )
    except PayPalAuthError as exc:
        logger.error("PayPal auth failure: %s", exc.message)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PayPal authentication failure: {exc.message}",
        ) from exc
    except PayPalConnectionError as exc:
        logger.error("PayPal connection error: %s", exc.message)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="PayPal service timed out or connection failed. Please retry.",
        ) from exc
    except PayPalOrderError as exc:
        logger.error("PayPal order creation error: %s", exc.message)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PayPal order creation failed: {exc.message}",
        ) from exc

    # Persist PayPal order ID and update status
    payment.paypal_order_id = order_data["id"]
    payment.status = PaymentStatus.ORDER_CREATED
    db.commit()
    db.refresh(payment)

    resp = PaymentResponse.model_validate(payment)
    resp.approval_url = order_data.get("approval_url")
    return resp


@router.post(
    "/{payment_id}/capture",
    response_model=PaymentResponse,
    summary="Capture a PayPal payment (Tanay implements)",
)
def capture_payment(
    payment_id: uuid.UUID,
    body: PaymentCaptureRequest,
    db: Session = Depends(get_db),
    service: PayPalService = Depends(get_paypal_service),
):
    """Capture an authorized/approved PayPal payment.

    - Validates payment existence and status is ORDER_CREATED.
    - Validates order ID matches the order stored on the payment record.
    - Executes capture against PayPal Orders API v2.
    - Verifies capture status is COMPLETED.
    - Verifies captured amount and currency match database record.
    - Updates payment record with paypal_capture_id and status CAPTURED (or FAILED).
    """
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found.")

    if payment.status == PaymentStatus.CAPTURED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment already captured.")

    if payment.status != PaymentStatus.ORDER_CREATED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Payment is in '{payment.status.value}' state. Can only capture 'order_created' payments.",
        )

    # Prevent cross-order or duplicate captures by verifying order ID matches
    if payment.paypal_order_id and payment.paypal_order_id != body.paypal_order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PayPal order ID does not match the payment record.",
        )

    try:
        capture_result = service.capture_order(
            order_id=body.paypal_order_id,
            idempotency_key=f"capture_{payment.id}_{body.paypal_order_id}",
        )
    except PayPalAuthError as exc:
        logger.error("PayPal auth failure during capture: %s", exc.message)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PayPal authentication failure: {exc.message}",
        ) from exc
    except PayPalConnectionError as exc:
        logger.error("PayPal connection error during capture: %s", exc.message)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="PayPal service timed out during capture. Please retry.",
        ) from exc
    except PayPalCaptureError as exc:
        logger.error("PayPal capture failed: %s", exc.message)
        payment.status = PaymentStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PayPal payment capture failed: {exc.message}",
        ) from exc

    # Server-Side Verification: Ensure capture status is COMPLETED
    capture_status = (capture_result.get("status") or "").upper()
    if capture_status != "COMPLETED":
        payment.status = PaymentStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PayPal capture status '{capture_status}' is not COMPLETED.",
        )

    # Server-Side Verification: Ensure captured amount matches expected DB amount
    try:
        captured_amount_dec = Decimal(str(capture_result.get("captured_amount")))
        if captured_amount_dec != payment.amount:
            payment.status = PaymentStatus.FAILED
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Captured amount ({captured_amount_dec}) does not match "
                    f"expected database amount ({payment.amount})."
                ),
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
    captured_currency = (capture_result.get("captured_currency") or "").upper()
    if captured_currency != payment.currency.upper():
        payment.status = PaymentStatus.FAILED
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Captured currency ({captured_currency}) does not match "
                f"expected currency ({payment.currency})."
            ),
        )

    # All server-side checks passed: commit CAPTURED state
    payment.paypal_capture_id = capture_result["capture_id"]
    payment.status = PaymentStatus.CAPTURED
    db.commit()
    db.refresh(payment)
    return payment


@router.get(
    "/{payment_id}",
    response_model=PaymentResponse,
    summary="Get payment status",
)
def get_payment(payment_id: uuid.UUID, db: Session = Depends(get_db)):
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found.")
    return payment
