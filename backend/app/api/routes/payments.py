"""Payment endpoints — interface only. Tanay owns the PayPal integration."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import Payment, PaymentStatus, User
from app.schemas.schemas import (
    PaymentCaptureRequest,
    PaymentCreateOrderRequest,
    PaymentResponse,
)
from app.services.authorization import require_payment_access

router = APIRouter(prefix="/api/payments", tags=["Payments"])


@router.post(
    "/{payment_id}/create-order",
    response_model=PaymentResponse,
    summary="Create a PayPal order for a payment (Tanay implements)",
)
def create_paypal_order(
    payment_id: uuid.UUID,
    body: PaymentCreateOrderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payment = require_payment_access(db, payment_id, current_user, require_payer=True)

    if payment.status != PaymentStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Payment is in '{payment.status.value}' state. Can only create order for 'pending' payments.",
        )

    if payment.paypal_order_id:
        raise HTTPException(
            status_code=409,
            detail="A PayPal order has already been created for this payment.",
        )

    # -----------------------------------------------------------------------
    # TODO (Tanay): Integrate PayPal Orders API here.
    #
    # 1. Call PayPal Create Order endpoint with payment.amount and payment.currency.
    # 2. Set payment.paypal_order_id = response order ID.
    # 3. Set payment.status = PaymentStatus.ORDER_CREATED.
    # 4. Commit and return updated payment.
    #
    # Do NOT mark payment as captured here.
    # -----------------------------------------------------------------------

    raise HTTPException(
        status_code=501,
        detail="PayPal order creation not implemented. Tanay will integrate this.",
    )


@router.post(
    "/{payment_id}/capture",
    response_model=PaymentResponse,
    summary="Capture a PayPal payment (Tanay implements)",
)
def capture_payment(
    payment_id: uuid.UUID,
    body: PaymentCaptureRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    payment = require_payment_access(db, payment_id, current_user, require_payer=True)

    if payment.status == PaymentStatus.CAPTURED:
        raise HTTPException(status_code=409, detail="Payment already captured.")

    if payment.status != PaymentStatus.ORDER_CREATED:
        raise HTTPException(
            status_code=409,
            detail=f"Payment is in '{payment.status.value}' state. Can only capture 'order_created' payments.",
        )

    # Prevent duplicate captures by verifying order ID matches
    if payment.paypal_order_id and payment.paypal_order_id != body.paypal_order_id:
        raise HTTPException(
            status_code=400,
            detail="PayPal order ID does not match the payment record.",
        )

    # -----------------------------------------------------------------------
    # TODO (Tanay): Integrate PayPal Capture endpoint here.
    #
    # 1. Call PayPal Capture Order endpoint with body.paypal_order_id.
    # 2. Verify capture was successful server-side (never trust frontend).
    # 3. Set payment.paypal_capture_id = response capture ID.
    # 4. Set payment.status = PaymentStatus.CAPTURED.
    # 5. Commit and return updated payment.
    #
    # On failure: set payment.status = PaymentStatus.FAILED and commit.
    # -----------------------------------------------------------------------

    raise HTTPException(
        status_code=501,
        detail="PayPal capture not implemented. Tanay will integrate this.",
    )


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

