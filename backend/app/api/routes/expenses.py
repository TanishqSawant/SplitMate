"""Expense endpoints: create, retrieve, assign items, calculate splits, and initialize payments."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import (
    Expense,
    ExpenseAssignment,
    ExpenseGroup,
    GroupMember,
    Payment,
    PaymentStatus,
    Receipt,
    ReceiptItem,
    ExtractionStatus,
)
from app.schemas.schemas import (
    AssignmentBatchRequest,
    AssignmentResponse,
    ExpenseCreate,
    ExpenseResponse,
    MemberSplit,
    PaymentResponse,
    SplitsResponse,
)
from app.services.split_calculator import calculate_splits_for_expense, is_expense_fully_assigned

router = APIRouter(prefix="/api/expenses", tags=["Expenses"])


@router.post(
    "",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an expense linked to a group and optionally a receipt",
)
def create_expense(body: ExpenseCreate, db: Session = Depends(get_db)):
    # Validate group
    group = db.get(ExpenseGroup, body.group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found.")

    # Fix 1: Validate receipt if provided
    if body.receipt_id:
        receipt = db.get(Receipt, body.receipt_id)
        if not receipt:
            raise HTTPException(status_code=404, detail="Receipt not found.")

        # Receipt extraction must be complete before an expense can be created
        if receipt.extraction_status != ExtractionStatus.COMPLETED:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Receipt extraction has not completed yet. "
                    "Wait for AI extraction to finish before creating an expense."
                ),
            )

        # If the receipt has an extracted total, the submitted amount must match exactly
        if receipt.total is not None:
            submitted = Decimal(str(body.total_amount))
            extracted = Decimal(str(receipt.total))
            if submitted != extracted:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Expense total ({submitted}) does not match the extracted receipt total "
                        f"({extracted}). Use the extracted total or correct the receipt first."
                    ),
                )

    expense = Expense(
        group_id=body.group_id,
        receipt_id=body.receipt_id,
        total_amount=body.total_amount,
        currency=body.currency,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.get(
    "/{expense_id}",
    response_model=ExpenseResponse,
    summary="Get an expense by ID",
)
def get_expense(expense_id: uuid.UUID, db: Session = Depends(get_db)):
    expense = db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")
    return expense


@router.post(
    "/{expense_id}/assign",
    response_model=list[AssignmentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Batch-assign receipt items to group members",
)
def assign_items(
    expense_id: uuid.UUID,
    body: AssignmentBatchRequest,
    db: Session = Depends(get_db),
):
    expense = db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")

    # Map existing assignments for upsert and quantity tracking
    existing_map: dict[tuple[uuid.UUID, uuid.UUID], ExpenseAssignment] = {
        (a.receipt_item_id, a.member_id): a for a in expense.assignments
    }

    # Simulate updated quantities per item to enforce capacity limits
    # Start with existing assigned quantities
    simulated_totals: dict[uuid.UUID, Decimal] = {}
    for a in expense.assignments:
        simulated_totals[a.receipt_item_id] = (
            simulated_totals.get(a.receipt_item_id, Decimal("0")) + a.share_quantity
        )

    # Validate all incoming assignments before persisting
    items_cache: dict[uuid.UUID, ReceiptItem] = {}

    for a in body.assignments:
        # Validate receipt item
        item = items_cache.get(a.receipt_item_id)
        if not item:
            item = db.get(ReceiptItem, a.receipt_item_id)
            if not item:
                raise HTTPException(
                    status_code=404,
                    detail=f"Receipt item {a.receipt_item_id} not found.",
                )
            items_cache[a.receipt_item_id] = item

        # Verify receipt item belongs to the expense's receipt (Cross-Group / Cross-Receipt Protection)
        if expense.receipt_id and item.receipt_id != expense.receipt_id:
            raise HTTPException(
                status_code=400,
                detail=f"Receipt item '{item.item_name}' does not belong to the receipt associated with this expense.",
            )

        # Validate member belongs to the expense's group (Cross-Group Protection)
        member = db.get(GroupMember, a.member_id)
        if not member or member.group_id != expense.group_id:
            raise HTTPException(
                status_code=400,
                detail=f"Member {a.member_id} is not part of this expense's group.",
            )

        # Prevent splitting an item if its price or quantity data is insufficient
        if item.quantity is None or item.total_price is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Receipt item '{item.item_name}' cannot be split due to insufficient price or quantity data. "
                    "Complete receipt review first."
                ),
            )

        # Update simulated total for capacity checking
        existing = existing_map.get((a.receipt_item_id, a.member_id))
        prior_qty = existing.share_quantity if existing else Decimal("0")
        current_total = simulated_totals.get(a.receipt_item_id, Decimal("0"))
        new_total = current_total - prior_qty + a.share_quantity
        simulated_totals[a.receipt_item_id] = new_total

        # Capacity Check: Cannot assign more than purchased
        if new_total > Decimal(str(item.quantity)):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Total assigned quantity ({new_total}) for item '{item.item_name}' "
                    f"exceeds purchased quantity ({item.quantity})."
                ),
            )

    # Persist or update assignments
    results: list[ExpenseAssignment] = []
    for a in body.assignments:
        existing = existing_map.get((a.receipt_item_id, a.member_id))
        if existing:
            existing.share_quantity = a.share_quantity
            results.append(existing)
        else:
            assignment = ExpenseAssignment(
                expense_id=expense_id,
                receipt_item_id=a.receipt_item_id,
                member_id=a.member_id,
                share_quantity=a.share_quantity,
            )
            db.add(assignment)
            results.append(assignment)

    db.commit()
    for r in results:
        db.refresh(r)
    return results


@router.get(
    "/{expense_id}/splits",
    response_model=SplitsResponse,
    summary="Calculate each member's share based on assignments (Idempotent, Read-Only)",
)
def get_splits(expense_id: uuid.UUID, db: Session = Depends(get_db)):
    expense = db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")

    calculated = calculate_splits_for_expense(expense, db)

    splits = [
        MemberSplit(
            member_id=c.member_id,
            member_name=c.member_name,
            member_email=c.member_email,
            allocated_subtotal=c.allocated_subtotal,
            allocated_tax=c.allocated_tax,
            amount=c.amount,
            currency=c.currency,
        )
        for c in calculated
    ]

    return SplitsResponse(
        expense_id=expense.id,
        total_amount=expense.total_amount,
        currency=expense.currency,
        splits=splits,
    )


@router.post(
    "/{expense_id}/initialize-payments",
    response_model=list[PaymentResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Initialize or update pending payments for each member in the split",
)
def initialize_payments(expense_id: uuid.UUID, db: Session = Depends(get_db)):
    expense = db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")

    # Fix 4: Block payment initialization if any receipt items are unassigned / partially assigned
    if expense.receipt_id:
        fully_assigned, unassigned_details = is_expense_fully_assigned(expense)
        if not fully_assigned:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Cannot initialize payments: some receipt items have not been fully assigned. "
                    + unassigned_details
                ),
            )

    # Check existing payments for payment safety
    existing_payments = (
        db.query(Payment).filter(Payment.expense_id == expense_id).all()
    )

    # Guard: Prevent overwriting payments that are already in flight or captured
    for p in existing_payments:
        if p.status in (PaymentStatus.ORDER_CREATED, PaymentStatus.CAPTURED):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot re-initialize payments: payment for member {p.member_id} "
                    f"is already in state '{p.status.value}'."
                ),
            )

    # Compute latest splits
    calculated_splits = calculate_splits_for_expense(expense, db)
    existing_by_member = {p.member_id: p for p in existing_payments}
    active_member_ids = {s.member_id for s in calculated_splits}

    # Delete pending payments for members who are no longer in the split
    for p in existing_payments:
        if p.member_id not in active_member_ids:
            db.delete(p)

    # Create or update payments
    results: list[Payment] = []
    for split in calculated_splits:
        # Enforce positive payment amount
        if split.amount <= Decimal("0"):
            continue

        existing = existing_by_member.get(split.member_id)
        if existing:
            existing.amount = split.amount
            existing.currency = split.currency
            results.append(existing)
        else:
            payment = Payment(
                expense_id=expense_id,
                member_id=split.member_id,
                amount=split.amount,
                currency=split.currency,
                status=PaymentStatus.PENDING,
            )
            db.add(payment)
            results.append(payment)

    db.commit()
    for r in results:
        db.refresh(r)
    return results
