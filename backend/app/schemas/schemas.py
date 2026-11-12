"""Pydantic schemas for request/response validation."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


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
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    total_price: Decimal | None = None

    model_config = {"from_attributes": True}


class ReceiptResponse(BaseModel):
    id: UUID
    original_filename: str
    merchant_name: str | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    extraction_status: str
    created_at: datetime
    items: list[ReceiptItemResponse] = []

    model_config = {"from_attributes": True}


class ReceiptItemExtraction(BaseModel):
    """A single extracted item from the receipt (sent by Pawan's AI service)."""
    item_name: str = Field(..., min_length=1, max_length=255)
    quantity: Decimal | None = Field(default=None, gt=0)
    unit_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    total_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)


class ReceiptExtractionRequest(BaseModel):
    """Payload that Pawan's AI extraction service submits after processing a receipt."""
    merchant_name: str | None = Field(default=None, max_length=255, examples=["Mario's Pizzeria"])
    currency: str | None = Field(default=None, max_length=3)
    subtotal: Decimal | None = Field(default=None, ge=0, decimal_places=2, examples=[45.50])
    tax: Decimal | None = Field(default=None, ge=0, decimal_places=2, examples=[3.64])
    total: Decimal | None = Field(default=None, ge=0, decimal_places=2, examples=[49.14])
    items: list[ReceiptItemExtraction] = Field(default_factory=list)
    extraction_status: str | None = Field(default=None, description="AI extraction status: completed, review_required, or failed")
    status: str | None = Field(default=None, description="Alias for extraction_status")

    @field_validator("merchant_name", mode="before")
    @classmethod
    def clean_merchant_name(cls, v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, str):
            stripped = v.strip()
            return stripped if stripped else None
        return str(v)

    @field_validator("currency", mode="before")
    @classmethod
    def clean_currency(cls, v: Any) -> str | None:
        if v is None or v == "":
            return None
        return str(v).strip().upper()

    @model_validator(mode="before")
    @classmethod
    def sync_status_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "status" in data and not data.get("extraction_status"):
                data["extraction_status"] = data["status"]
            elif "extraction_status" in data and not data.get("status"):
                data["status"] = data["extraction_status"]
        return data


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
    pass  # payment_id is in the URL path


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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    detail: str

