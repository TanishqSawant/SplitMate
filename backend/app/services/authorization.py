"""Authorization and IDOR protection service.

Validates that an authenticated user has legitimate access to groups, receipts,
expenses, assignments, and payments via verified database relationships.
Avoids leaking the existence of other users' resources by returning 404.
"""

import uuid
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.models import (
    Expense,
    ExpenseGroup,
    GroupMember,
    Payment,
    Receipt,
    User,
)


def is_user_group_member(db: Session, group: ExpenseGroup, user: User) -> bool:
    """Check whether a user is an authorized member or the creator of a group."""
    if group.creator_id is not None and group.creator_id == user.id:
        return True

    user_email_normalized = user.email.strip().lower()
    for member in group.members:
        if member.user_id is not None and member.user_id == user.id:
            return True
        if member.email and member.email.strip().lower() == user_email_normalized:
            return True

    return False


def require_group_membership(
    db: Session, group_id: uuid.UUID, user: User
) -> ExpenseGroup:
    """Ensure the user is a legitimate member or creator of the expense group.

    Returns the ExpenseGroup if authorized.
    Raises HTTP 404 if the group does not exist or if the user is not a member,
    preventing IDOR and resource-enumeration leaks.
    """
    group = db.get(ExpenseGroup, group_id)
    if not group or not is_user_group_member(db, group, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found.",
        )
    return group


def require_receipt_access(
    db: Session, receipt_id: uuid.UUID, user: User
) -> Receipt:
    """Ensure the user has permission to access a receipt.

    A user can access a receipt if:
    1. They uploaded it (receipt.uploader_id == user.id), OR
    2. The receipt is linked to an expense in a group where they are an authorized member.

    Returns the Receipt if authorized.
    Raises HTTP 404 if not found or unauthorized.
    """
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Receipt not found.",
        )

    # 1. Direct uploader access
    if receipt.uploader_id is not None and receipt.uploader_id == user.id:
        return receipt

    # 2. Access through linked group expense
    for expense in receipt.expenses:
        if expense.group and is_user_group_member(db, expense.group, user):
            return receipt

    # If neither, reject with 404 to avoid leaking existence
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Receipt not found.",
    )


def require_expense_access(
    db: Session, expense_id: uuid.UUID, user: User
) -> Expense:
    """Ensure the user is an authorized member of the group owning the expense.

    Returns the Expense if authorized.
    Raises HTTP 404 if not found or unauthorized.
    """
    expense = db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Expense not found.",
        )

    require_group_membership(db, expense.group_id, user)
    return expense


def require_payment_access(
    db: Session,
    payment_id: uuid.UUID,
    user: User,
    require_payer: bool = False,
) -> Payment:
    """Ensure the user is authorized to view or perform actions on a payment.

    If require_payer is True (e.g., initiating PayPal order, capturing payment):
      - The user MUST be the specific member responsible for the payment.
      - Non-payers are rejected with HTTP 403 Forbidden.

    If require_payer is False (e.g., viewing payment status):
      - The paying member OR any member of the group may view payment status.
      - Unrelated users are rejected with HTTP 404 Not Found.
    """
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found.",
        )

    user_email_normalized = user.email.strip().lower()
    is_payer = False
    if payment.member:
        if payment.member.user_id is not None and payment.member.user_id == user.id:
            is_payer = True
        elif (
            payment.member.email
            and payment.member.email.strip().lower() == user_email_normalized
        ):
            is_payer = True

    if require_payer:
        if not is_payer:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only manage or pay your own share.",
            )
        return payment

    # Read access: payer or any group member
    if is_payer:
        return payment

    if payment.expense and payment.expense.group:
        if is_user_group_member(db, payment.expense.group, user):
            return payment

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Payment not found.",
    )

