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
        ..., min_length=6, max_length=128, description="Password must be at least 6 characters"
    )
    paypal_email: str | None = Field(default=None, max_length=320)
    avatar: str | None = Field(default=None, max_length=500)


UserRegisterRequest = UserRegister


class UserLogin(BaseModel):
    email: EmailStr = Field(..., examples=["tanishq@example.com"])
    password: str = Field(..., min_length=1, max_length=128)


UserLoginRequest = UserLogin


class UserProfileUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    paypal_email: str | None = Field(default=None, max_length=320)
    avatar: str | None = Field(default=None, max_length=500)


class UserResponse(BaseModel):
    id: UUID
    name: str
    email: str
    paypal_email: str | None = None
    avatar: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


AuthTokenResponse = TokenResponse


# ---------------------------------------------------------------------------
# ExpenseGroup
# ---------------------------------------------------------------------------

class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["Dinner at Mario's"])


class GroupUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, examples=["Dinner at Mario's (Updated)"])


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
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    total_price: Decimal | None = None

    model_config = {"from_attributes": True}


class ReceiptResponse(BaseModel):
    receipt_id: UUID
    original_filename: str
    document_type: str | None = None
    merchant_name: str | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
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

    @model_validator(mode="before")
    @classmethod
    def map_id_to_receipt_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "receipt_id" not in data and "id" in data:
                data["receipt_id"] = data["id"]
        return data

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
            id=receipt.id,
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


class ReceiptItemUpdate(BaseModel):
    id: UUID | None = None
    item_name: str = Field(..., min_length=1, max_length=255)
    quantity: Decimal = Field(default=Decimal("1"), gt=0, description="Positive quantity, may be fractional (e.g. 0.5 kg)")
    unit_price: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    total_price: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)


class ReceiptItemsUpdateRequest(BaseModel):
    merchant_name: str | None = None
    currency: str | None = None
    tax: Decimal | None = None
    items: list[ReceiptItemUpdate] = Field(..., min_length=1)


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
    total: Decimal = Field(..., gt=0, decimal_places=2, description="Final confirmed total ΓÇö must be positive")
    items: list[ReceiptItemReview] = Field(..., min_length=1, description="Reviewed line items ΓÇö at least one required")


class SampleReceiptItem(BaseModel):
    name: str
    price: Decimal
    quantity: int = 1


class SampleReceiptResponse(BaseModel):
    id: str
    name: str
    merchant: str
    date: str
    total: Decimal
    category: str
    items: list[SampleReceiptItem]


# ---------------------------------------------------------------------------
# Expense
# ---------------------------------------------------------------------------

class ExpenseCreate(BaseModel):
    group_id: UUID
    receipt_id: UUID | None = None
    total_amount: Decimal = Field(..., gt=0, decimal_places=2)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class ExpenseUpdate(BaseModel):
    total_amount: Decimal | None = Field(default=None, gt=0, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


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


class PaymentDirectCreateOrderRequest(BaseModel):
    """Payload for frontend compatibility calling /api/payments/paypal/create-order."""

    payment_id: UUID | None = Field(default=None, alias="paymentId")
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
    payment_id: UUID | None = Field(default=None, alias="paymentId")
    payer_id: UUID | None = Field(default=None, alias="payerId")
    amount: Decimal | None = None

    model_config = {"populate_by_name": True}
