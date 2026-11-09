"""Pydantic schemas for request/response validation."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


# ---------------------------------------------------------------------------
# ExpenseGroup
# ---------------------------------------------------------------------------

class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["Dinner at Mario's"])


class GroupResponse(BaseModel):
    id: UUID
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# GroupMember
# ---------------------------------------------------------------------------

class MemberCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["Tanishq"])
    email: EmailStr = Field(..., examples=["tanishq@example.com"])


class MemberResponse(BaseModel):
    id: UUID
    group_id: UUID
    name: str
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Receipt & ReceiptItem
# ---------------------------------------------------------------------------

class ReceiptItemResponse(BaseModel):
    id: UUID
    receipt_id: UUID
    item_name: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal

    model_config = {"from_attributes": True}


class ReceiptResponse(BaseModel):
    id: UUID
    original_filename: str
    merchant_name: str | None
    currency: str
    subtotal: Decimal | None
    tax: Decimal | None
    total: Decimal | None
    extraction_status: str
    created_at: datetime
    items: list[ReceiptItemResponse] = []

    model_config = {"from_attributes": True}


class ReceiptItemExtraction(BaseModel):
    """A single extracted item from the receipt (sent by Pawan's AI service)."""
    item_name: str = Field(..., min_length=1, max_length=255)
    quantity: int = Field(..., ge=1)
    unit_price: Decimal = Field(..., ge=0, decimal_places=2)
    total_price: Decimal = Field(..., ge=0, decimal_places=2)


class ReceiptExtractionRequest(BaseModel):
    """Payload that Pawan's AI extraction service submits after processing a receipt."""
    merchant_name: str = Field(..., min_length=1, max_length=255, examples=["Mario's Pizzeria"])
    currency: str = Field(default="USD", min_length=3, max_length=3)
    subtotal: Decimal = Field(..., ge=0, decimal_places=2, examples=[45.50])
    tax: Decimal = Field(..., ge=0, decimal_places=2, examples=[3.64])
    total: Decimal = Field(..., ge=0, decimal_places=2, examples=[49.14])
    items: list[ReceiptItemExtraction] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Expense
# ---------------------------------------------------------------------------

class ExpenseCreate(BaseModel):
    group_id: UUID
    receipt_id: UUID | None = None
    total_amount: Decimal = Field(..., gt=0, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class ExpenseResponse(BaseModel):
    id: UUID
    group_id: UUID
    receipt_id: UUID | None
    total_amount: Decimal
    currency: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# ExpenseAssignment
# ---------------------------------------------------------------------------

class AssignmentCreate(BaseModel):
    receipt_item_id: UUID
    member_id: UUID
    share_quantity: Decimal = Field(
        default=Decimal("1"),
        gt=0,
        description="Portion of the item assigned to this member (e.g. 0.5 for half).",
    )


class AssignmentBatchRequest(BaseModel):
    """Batch-assign receipt items to members for an expense."""
    assignments: list[AssignmentCreate] = Field(..., min_length=1)


class AssignmentResponse(BaseModel):
    id: UUID
    expense_id: UUID
    receipt_item_id: UUID
    member_id: UUID
    share_quantity: Decimal

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Splits (calculated share per member)
# ---------------------------------------------------------------------------

class MemberSplit(BaseModel):
    member_id: UUID
    member_name: str
    member_email: str
    allocated_subtotal: Decimal | None = Field(
        default=None, description="Proportional item subtotal before tax and extra fees."
    )
    allocated_tax: Decimal | None = Field(
        default=None, description="Proportional share of tax, tip, and extra fees."
    )
    amount: Decimal = Field(..., description="This member's final reconciled share of the expense.")
    currency: str


class SplitsResponse(BaseModel):
    expense_id: UUID
    total_amount: Decimal
    currency: str
    splits: list[MemberSplit]


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------

class PaymentCreateOrderRequest(BaseModel):
    """Triggers PayPal order creation. Tanay implements the actual integration."""
    return_url: str | None = None
    cancel_url: str | None = None


class PaymentCaptureRequest(BaseModel):
    """Triggers PayPal capture. Tanay implements the actual integration."""
    paypal_order_id: str = Field(..., min_length=1, max_length=50)


class PaymentResponse(BaseModel):
    id: UUID
    expense_id: UUID
    member_id: UUID
    amount: Decimal
    currency: str
    paypal_order_id: str | None
    paypal_capture_id: str | None
    status: str
    approval_url: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaymentDirectCreateOrderRequest(BaseModel):
    """Payload for frontend compatibility calling /api/payments/paypal/create-order."""
    payment_id: UUID | None = None
    payer_id: UUID | None = Field(default=None, alias="payerId")
    expense_id: UUID | None = Field(default=None, alias="expenseId")
    receiver_email: str | None = Field(default=None, alias="receiverEmail")
    amount: Decimal | None = None
    currency: str | None = "USD"
    note: str | None = None

    model_config = {"populate_by_name": True}


class PaymentDirectCaptureRequest(BaseModel):
    """Payload for frontend compatibility calling /api/payments/paypal/capture-order."""
    order_id: str = Field(..., alias="orderId", min_length=1, max_length=50)
    payment_id: UUID | None = None
    payer_id: UUID | None = Field(default=None, alias="payerId")
    amount: Decimal | None = None

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    detail: str

