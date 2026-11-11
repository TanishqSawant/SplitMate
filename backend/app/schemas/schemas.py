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
# User & Authentication
# ---------------------------------------------------------------------------

class UserRegister(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["Tanishq"])
    email: EmailStr = Field(..., examples=["tanishq@example.com"])
    password: str = Field(
        ..., min_length=8, max_length=128, description="Password must be at least 8 characters"
    )


class UserLogin(BaseModel):
    email: EmailStr = Field(..., examples=["tanishq@example.com"])
    password: str = Field(..., min_length=1, max_length=128)


class UserResponse(BaseModel):
    id: UUID
    name: str
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# ---------------------------------------------------------------------------
# ExpenseGroup
# ---------------------------------------------------------------------------

class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["Dinner at Mario's"])


class GroupResponse(BaseModel):
    id: UUID
    name: str
    creator_id: UUID | None = None
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
    user_id: UUID | None = None
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
    quantity: Decimal | None
    unit_price: Decimal | None
    total_price: Decimal | None

    model_config = {"from_attributes": True}


class ReceiptResponse(BaseModel):
    receipt_id: UUID
    original_filename: str
    document_type: str | None = None
    merchant_name: str | None
    currency: str | None
    subtotal: Decimal | None
    tax: Decimal | None
    total: Decimal | None
    extraction_status: str
    missing_fields: list[str] | None = None
    uncertain_fields: list[str] | None = None
    warnings: list[str] | None = None
    confidence: float | None = None
    error_code: str | None = None
    error_message: str | None = None
    is_user_reviewed: bool = False
    created_at: datetime
    items: list[ReceiptItemResponse] = []

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_receipt(cls, receipt: Any) -> "ReceiptResponse":
        """Build a ReceiptResponse from an ORM Receipt, deserializing JSON fields."""
        import json

        def _parse_json_list(val: str | None) -> list[str] | None:
            if val is None:
                return None
            try:
                parsed = json.loads(val)
                return parsed if isinstance(parsed, list) else None
            except Exception:
                return None

        return cls(
            receipt_id=receipt.id,
            original_filename=receipt.original_filename,
            document_type=getattr(receipt, "document_type", None),
            merchant_name=receipt.merchant_name,
            currency=receipt.currency,
            subtotal=receipt.subtotal,
            tax=receipt.tax,
            total=receipt.total,
            extraction_status=receipt.extraction_status,
            missing_fields=_parse_json_list(receipt.missing_fields),
            uncertain_fields=_parse_json_list(receipt.uncertain_fields),
            warnings=_parse_json_list(receipt.warnings),
            confidence=receipt.confidence,
            error_code=receipt.error_code,
            error_message=receipt.error_message,
            is_user_reviewed=receipt.is_user_reviewed,
            created_at=receipt.created_at,
            items=receipt.items,
        )


class ReceiptItemExtraction(BaseModel):
    """A single extracted item from the receipt (sent by Pawan's AI service)."""
    item_name: str | None = Field(default=None, max_length=255)
    quantity: Decimal | None = Field(default=None, gt=0, description="Positive quantity, may be fractional (e.g. 0.5 kg)")
    unit_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    total_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)


class ReceiptExtractionRequest(BaseModel):
    """Payload that Pawan's AI extraction service submits after processing a receipt."""
    merchant_name: str | None = Field(default=None, max_length=255, examples=["Mario's Pizzeria"])
    currency: str | None = Field(default=None, max_length=3)
    subtotal: Decimal | None = Field(default=None, decimal_places=2, examples=[45.50])
    tax: Decimal | None = Field(default=None, decimal_places=2, examples=[3.64])
    total: Decimal | None = Field(default=None, decimal_places=2, examples=[49.14])
    items: list[ReceiptItemExtraction] = Field(default_factory=list)
    missing_fields: list[str] | None = None
    uncertain_fields: list[str] | None = None
    warnings: list[str] | None = None
    confidence: float | None = None
    document_type: str | None = None


# ---------------------------------------------------------------------------
# Receipt Extraction Initiation
# ---------------------------------------------------------------------------

class ReceiptExtractInitiatedResponse(BaseModel):
    """Returned immediately after POST /api/receipts/extract is accepted."""
    receipt_id: UUID
    extraction_status: str


# ---------------------------------------------------------------------------
# Receipt Review Submission
# ---------------------------------------------------------------------------

class ReceiptItemReview(BaseModel):
    """A single item submitted during human review of a receipt."""
    item_name: str = Field(..., min_length=1, max_length=255)
    quantity: Decimal = Field(..., gt=0, description="Positive quantity, may be fractional (e.g. 0.5 kg)")
    unit_price: Decimal = Field(..., ge=0, decimal_places=2)
    total_price: Decimal = Field(..., ge=0, decimal_places=2)


class ReceiptReviewSubmission(BaseModel):
    """Payload for PUT /api/receipts/{receipt_id}/review to manually correct extraction results."""
    merchant_name: str | None = Field(default=None, max_length=255)
    currency: str = Field(..., min_length=3, max_length=3, description="3-letter ISO currency code")
    subtotal: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    tax: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    total: Decimal = Field(..., gt=0, decimal_places=2, description="Final confirmed total — must be positive")
    items: list[ReceiptItemReview] = Field(..., min_length=1, description="Reviewed line items — at least one required")


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
    """Triggers PayPal order creation."""
    return_url: str | None = None
    cancel_url: str | None = None


class PaymentCaptureRequest(BaseModel):
    """Triggers PayPal capture."""
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


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    detail: str

