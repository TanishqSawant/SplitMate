"""Payment endpoints — PayPal Sandbox integration with JWT authentication and IDOR protection."""

from decimal import Decimal
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.models import GroupMember, Payment, PaymentStatus, User
from app.schemas.schemas import (
    PaymentCaptureRequest,
    PaymentCreateOrderRequest,
    PaymentDirectCaptureRequest,
    PaymentDirectCreateOrderRequest,
    PaymentResponse,
)
from app.services.authorization import is_user_group_member, require_payment_access
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
def list_payments(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return payment transactions that the authenticated user is authorized to view.

    Includes payments where:
    1. The authenticated user is the paying member (user_id or email match), OR
    2. The payment belongs to an expense in a group where the user is an authorized member or creator.
    """
    normalized_email = current_user.email.strip().lower()

    all_payments = db.query(Payment).order_by(Payment.created_at.desc()).limit(200).all()
    authorized: list[Payment] = []
    for p in all_payments:
        # Check if caller is payer
        if p.member:
            if p.member.user_id is not None and p.member.user_id == current_user.id:
                authorized.append(p)
                continue
            if p.member.email and p.member.email.strip().lower() == normalized_email:
                authorized.append(p)
                continue
        # Check if caller belongs to the expense's group
        if p.expense and p.expense.group and is_user_group_member(db, p.expense.group, current_user):
            authorized.append(p)

    return authorized[:100]


@router.post(
    "/paypal/create-order",
    response_model=PaymentResponse,
    summary="Create PayPal order (Frontend compatibility route)",
)
def create_paypal_order_direct(
    body: PaymentDirectCreateOrderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
    else:
        normalized_email = current_user.email.strip().lower()
        payment = (
            db.query(Payment)
            .join(Payment.member)
            .filter(
                (GroupMember.user_id == current_user.id) | (func.lower(GroupMember.email) == normalized_email),
                Payment.status == PaymentStatus.PENDING,
            )
            .order_by(Payment.created_at.desc())
            .first()
        )

    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending payment record found matching the provided parameters.",
        )

    # Enforce caller authorization: caller must be the payer
    require_payment_access(db, payment.id, current_user, require_payer=True)

    req = PaymentCreateOrderRequest(member_id=payment.member_id)
    return create_paypal_order(
        payment_id=payment.id,
        body=req,
        db=db,
        current_user=current_user,
        service=service,
    )


@router.post(
    "/paypal/capture-order",
    response_model=PaymentResponse,
    summary="Capture PayPal order (Frontend compatibility route)",
)
def capture_payment_direct(
    body: PaymentDirectCaptureRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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

    # Enforce caller authorization: caller must be the payer
    require_payment_access(db, payment.id, current_user, require_payer=True)

    req = PaymentCaptureRequest(paypal_order_id=body.order_id, member_id=payment.member_id)
    return capture_payment(
        payment_id=payment.id,
        body=req,
        db=db,
        current_user=current_user,
        service=service,
    )


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
    current_user: User = Depends(get_current_user),
    service: PayPalService = Depends(get_paypal_service),
):
    """Create a PayPal checkout order for a verified server-side pending payment.

    - Authenticates the caller and enforces require_payer=True.
    - Verifies payment existence in database with row-level locking.
    - Validates payment group membership integrity.
    - Ensures status is PENDING and no existing order is attached.
    - Uses server-side amount and currency (never trusts client amount).
    - Calls PayPal Orders API v2 (intent=CAPTURE) with idempotency key.
    - Records returned PayPal order ID and marks payment as ORDER_CREATED.
    - Executes database rollback on any commit failure.
    """
    # 1. Authorize: user must be the specific member responsible for this payment
    require_payment_access(db, payment_id, current_user, require_payer=True)

    # 2. Row-level locking
    payment = (
        db.query(Payment)
        .filter(Payment.id == payment_id)
        .with_for_update()
        .first()
    )
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found.")

    # 3. Ownership & Group Integrity Verification
    if payment.expense and payment.member:
        if payment.expense.group_id != payment.member.group_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Payment record has invalid group membership integrity.",
            )

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

    # 4. Call PayPal Orders API v2
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
    try:
        db.commit()
        db.refresh(payment)
    except Exception as db_exc:
        db.rollback()
        logger.exception("Database commit failed on create-order for payment %s: %s", payment.id, db_exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to commit payment order creation.",
        ) from db_exc

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
    current_user: User = Depends(get_current_user),
    service: PayPalService = Depends(get_paypal_service),
):
    """Capture an authorized/approved PayPal payment.

    - Authenticates caller and enforces require_payer=True.
    - Validates payment existence and status is ORDER_CREATED with row locking.
    - Validates group integrity.
    - Validates order ID matches the order stored on the payment record.
    - Executes capture against PayPal Orders API v2.
    - Automatic Reconciliation: If PayPal reports ORDER_ALREADY_CAPTURED or network times out,
      reconciles status from PayPal order details without prematurely marking failed.
    - Verifies capture status is COMPLETED.
    - Verifies captured amount and currency match database record.
    - Updates payment record with paypal_capture_id and status CAPTURED (or FAILED).
    - Ensures database rollback on any commit error.
    """
    # 1. Authorize: user must be the specific member responsible for this payment
    require_payment_access(db, payment_id, current_user, require_payer=True)

    # 2. Row-level locking
    payment = (
        db.query(Payment)
        .filter(Payment.id == payment_id)
        .with_for_update()
        .first()
    )
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found.")

    # 3. Ownership & Group Integrity Verification
    if payment.expense and payment.member:
        if payment.expense.group_id != payment.member.group_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Payment record has invalid group membership integrity.",
            )

    if payment.status == PaymentStatus.CAPTURED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment already captured.")

    if payment.status != PaymentStatus.ORDER_CREATED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Payment is in '{payment.status.value}' state. Can only capture 'order_created' payments.",
        )

    # 4. Prevent cross-order captures
    if payment.paypal_order_id and payment.paypal_order_id != body.paypal_order_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PayPal order ID does not match the payment record.",
        )

    capture_result = None
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
        # Network timeout does NOT mean payment failed — leave status as order_created
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="PayPal service timed out during capture. Please retry to reconcile status.",
        ) from exc
    except PayPalCaptureError as exc:
        logger.warning(
            "PayPal capture returned error for payment %s: %s. Attempting reconciliation...",
            payment.id,
            exc.message,
        )
        # Attempt reconciliation via order details before marking payment FAILED
        reconciled = False
        try:
            order_info = service.get_order_details(body.paypal_order_id)
            if (order_info.get("status") or "").upper() == "COMPLETED":
                capture_result = service._parse_order_capture(body.paypal_order_id, order_info)
                reconciled = True
                logger.info("Successfully reconciled capture from order details for payment %s", payment.id)
        except Exception as rec_err:
            logger.warning("Reconciliation check failed for payment %s: %s", payment.id, rec_err)

        if not reconciled:
            payment.status = PaymentStatus.FAILED
            try:
                db.commit()
            except Exception:
                db.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"PayPal payment capture failed: {exc.message}",
            ) from exc

    # Server-Side Verification: Ensure capture status is COMPLETED
    capture_status = (capture_result.get("status") or "").upper()
    if capture_status != "COMPLETED":
        payment.status = PaymentStatus.FAILED
        try:
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"PayPal capture status '{capture_status}' is not COMPLETED.",
        )

    # Server-Side Verification: Ensure captured amount matches expected DB amount
    try:
        captured_amount_dec = Decimal(str(capture_result.get("captured_amount")))
        if captured_amount_dec != payment.amount:
            payment.status = PaymentStatus.FAILED
            try:
                db.commit()
            except Exception:
                db.rollback()
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
        try:
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or missing captured amount in PayPal response.",
        ) from exc

    # Server-Side Verification: Ensure captured currency matches expected DB currency
    captured_currency = (capture_result.get("captured_currency") or "").upper()
    if captured_currency != payment.currency.upper():
        payment.status = PaymentStatus.FAILED
        try:
            db.commit()
        except Exception:
            db.rollback()
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
    try:
        db.commit()
        db.refresh(payment)
    except Exception as db_exc:
        db.rollback()
        logger.exception("Database commit failed on capture for payment %s: %s", payment.id, db_exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to commit payment capture.",
        ) from db_exc

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
