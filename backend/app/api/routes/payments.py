"""Payment endpoints for PayPal sandbox order creation, capture, and verification."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import Payment, PaymentStatus
from app.schemas.schemas import (
    PaymentCaptureRequest,
    PaymentCreateOrderRequest,
    PaymentResponse,
)
from app.services.paypal import paypal_service

router = APIRouter(prefix="/api/payments", tags=["Payments"])


@router.post(
    "/{payment_id}/create-order",
    response_model=PaymentResponse,
    summary="Create a PayPal order for a payment",
)
def create_paypal_order(
    payment_id: uuid.UUID,
    body: PaymentCreateOrderRequest | None = None,
    db: Session = Depends(get_db),
):
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")

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

    try:
        order_data = paypal_service.create_order(
            amount=payment.amount,
            currency=payment.currency,
            reference_id=str(payment.id),
        )
    except Exception as e:
        raise HTTPException(
            status_code=502, detail=f"PayPal order creation failed: {e}"
        )

    payment.paypal_order_id = order_data["id"]
    payment.status = PaymentStatus.ORDER_CREATED
    db.commit()
    db.refresh(payment)
    return payment


@router.post(
    "/{payment_id}/capture",
    response_model=PaymentResponse,
    summary="Capture a PayPal payment and verify server-side status",
)
def capture_payment(
    payment_id: uuid.UUID,
    body: PaymentCaptureRequest,
    db: Session = Depends(get_db),
):
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found.")

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

    try:
        capture_result = paypal_service.capture_payment(body.paypal_order_id)
    except Exception as e:
        payment.status = PaymentStatus.FAILED
        db.commit()
        raise HTTPException(status_code=502, detail=f"PayPal capture failed: {e}")

    if capture_result.get("status") == "COMPLETED":
        payment.paypal_capture_id = capture_result.get("capture_id")
        payment.status = PaymentStatus.CAPTURED
    else:
        payment.status = PaymentStatus.FAILED

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
        raise HTTPException(status_code=404, detail="Payment not found.")
    return payment


@router.get(
    "/expense/{expense_id}",
    response_model=list[PaymentResponse],
    summary="List all payments for an expense",
)
def list_expense_payments(expense_id: uuid.UUID, db: Session = Depends(get_db)):
    return db.query(Payment).filter(Payment.expense_id == expense_id).all()
