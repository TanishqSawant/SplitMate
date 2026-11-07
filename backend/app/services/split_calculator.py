"""Split calculation service ensuring financial accuracy and penny reconciliation."""

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
import uuid
from typing import NamedTuple

from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.models import Expense, ExpenseAssignment, GroupMember, ReceiptItem


class CalculatedSplit(NamedTuple):
    member_id: uuid.UUID
    member_name: str
    member_email: str
    allocated_subtotal: Decimal
    allocated_tax: Decimal
    amount: Decimal
    currency: str


def calculate_splits_for_expense(
    expense: Expense, db: Session
) -> list[CalculatedSplit]:
    """Calculate proportional shares for each assigned group member.

    Financial Accuracy Rules:
    1. All math is performed using Decimal.
    2. Items are allocated based on share_quantity.
    3. Tax and additional charges (expense.total_amount - subtotal) are apportioned
       pro-rata according to each member's share of the assigned item subtotal.
    4. Rounding difference reconciliation (Penny Allocation):
       The sum of all individual member shares is guaranteed to equal
       the target total_amount down to the exact cent. Any rounding residue (+/- cents)
       is allocated to the members with the largest rounding error.
    """
    if not expense.assignments:
        raise HTTPException(
            status_code=400, detail="No items have been assigned yet."
        )

    # 1. Group assignments by receipt_item_id
    item_assignments: dict[uuid.UUID, list[ExpenseAssignment]] = defaultdict(list)
    for assignment in expense.assignments:
        item_assignments[assignment.receipt_item_id].append(assignment)

    # 2. Calculate member raw item subtotals
    member_subtotals: dict[uuid.UUID, Decimal] = defaultdict(lambda: Decimal("0.00"))

    for item_id, assignments in item_assignments.items():
        item = db.get(ReceiptItem, item_id)
        if not item:
            continue

        total_shares = sum(a.share_quantity for a in assignments)
        if total_shares <= Decimal("0"):
            continue

        for a in assignments:
            # Proportional cost of this item for this assignment:
            # (item.total_price * share_quantity) / total_shares
            # Keep full precision here before final rounding
            share_cost = (item.total_price * a.share_quantity) / total_shares
            member_subtotals[a.member_id] += share_cost

    total_assigned_subtotal = sum(member_subtotals.values())
    if total_assigned_subtotal <= Decimal("0"):
        raise HTTPException(
            status_code=400, detail="Assigned items total zero amount."
        )

    # 3. Determine tax & extra charges
    # If a receipt is linked, receipt.total is the full bill with tax.
    # If all items are assigned, target total is expense.total_amount.
    target_total = expense.total_amount

    # Pro-rata tax distribution:
    # Each member's raw unrounded total share is:
    # raw_share = target_total * (member_subtotal / total_assigned_subtotal)
    raw_shares: dict[uuid.UUID, Decimal] = {}
    tax_shares: dict[uuid.UUID, Decimal] = {}

    for member_id, subtotal in member_subtotals.items():
        raw_share = (target_total * subtotal) / total_assigned_subtotal
        raw_shares[member_id] = raw_share
        tax_shares[member_id] = raw_share - subtotal

    # 4. Initial rounding to cents (ROUND_HALF_UP)
    cents = Decimal("0.01")
    rounded_shares: dict[uuid.UUID, Decimal] = {
        m_id: share.quantize(cents, rounding=ROUND_HALF_UP)
        for m_id, share in raw_shares.items()
    }

    # 5. Rounding Difference Reconciliation (Penny Allocation)
    current_sum = sum(rounded_shares.values())
    discrepancy = target_total - current_sum

    if discrepancy != Decimal("0.00"):
        # Determine number of cents to distribute (+ or -)
        penny = Decimal("0.01") if discrepancy > Decimal("0") else Decimal("-0.01")
        steps = int(abs(discrepancy) / Decimal("0.01"))

        # Sort members by remainder: (raw_share - rounded_share)
        # If discrepancy > 0, give penny to members who were rounded down the most (largest raw - rounded)
        # If discrepancy < 0, subtract penny from members who were rounded up the most (most negative raw - rounded)
        remainders = [
            (raw_shares[m_id] - rounded_shares[m_id], m_id)
            for m_id in rounded_shares
        ]
        remainders.sort(reverse=(discrepancy > Decimal("0")), key=lambda x: (x[0], str(x[1])))

        for i in range(min(steps, len(remainders))):
            m_id = remainders[i][1]
            rounded_shares[m_id] += penny

    # 6. Build the final calculated splits
    results: list[CalculatedSplit] = []
    for member_id, final_amount in rounded_shares.items():
        member = db.get(GroupMember, member_id)
        if not member:
            continue

        subtotal_rounded = member_subtotals[member_id].quantize(cents, rounding=ROUND_HALF_UP)
        tax_rounded = (final_amount - subtotal_rounded).quantize(cents, rounding=ROUND_HALF_UP)

        results.append(
            CalculatedSplit(
                member_id=member.id,
                member_name=member.name,
                member_email=member.email,
                allocated_subtotal=subtotal_rounded,
                allocated_tax=tax_rounded,
                amount=final_amount,
                currency=expense.currency,
            )
        )

    return results

