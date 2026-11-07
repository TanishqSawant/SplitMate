"""SQLAlchemy ORM models for SplitMate."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class UUID(TypeDecorator):
    """Platform-independent UUID type.

    Uses PostgreSQL's native UUID when available, otherwise stores as CHAR(32).
    This allows the same models to work with both PostgreSQL and SQLite (for testing).
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
        else:
            return value.hex if isinstance(value, uuid.UUID) else uuid.UUID(value).hex

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            return uuid.UUID(value)
        return value


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ExtractionStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class PaymentStatus(str, enum.Enum):
    PENDING = "pending"
    ORDER_CREATED = "order_created"
    CAPTURED = "captured"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ExpenseGroup(Base):
    __tablename__ = "expense_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    members: Mapped[list["GroupMember"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )
    expenses: Mapped[list["Expense"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class GroupMember(Base):
    __tablename__ = "group_members"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(), primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("expense_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    group: Mapped["ExpenseGroup"] = relationship(back_populates="members")
    assignments: Mapped[list["ExpenseAssignment"]] = relationship(
        back_populates="member", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="member", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_group_members_group_id", "group_id"),
        Index("ix_group_members_email", "email"),
    )


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(), primary_key=True, default=uuid.uuid4
    )
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_file_path: Mapped[str] = mapped_column(Text, nullable=False)
    merchant_name: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    subtotal: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    tax: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    extraction_status: Mapped[ExtractionStatus] = mapped_column(
        Enum(ExtractionStatus, name="extraction_status_enum"),
        default=ExtractionStatus.PENDING,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    items: Mapped[list["ReceiptItem"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )
    expenses: Mapped[list["Expense"]] = relationship(
        back_populates="receipt"
    )


class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(), primary_key=True, default=uuid.uuid4
    )
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("receipts.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(default=1, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    total_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    # Relationships
    receipt: Mapped["Receipt"] = relationship(back_populates="items")
    assignments: Mapped[list["ExpenseAssignment"]] = relationship(
        back_populates="receipt_item", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_receipt_items_receipt_id", "receipt_id"),
        CheckConstraint("quantity > 0", name="ck_receipt_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_receipt_items_unit_price_non_negative"),
        CheckConstraint("total_price >= 0", name="ck_receipt_items_total_price_non_negative"),
    )


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(), primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("expense_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    receipt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("receipts.id", ondelete="SET NULL"),
        nullable=True,
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    group: Mapped["ExpenseGroup"] = relationship(back_populates="expenses")
    receipt: Mapped["Receipt | None"] = relationship(back_populates="expenses")
    assignments: Mapped[list["ExpenseAssignment"]] = relationship(
        back_populates="expense", cascade="all, delete-orphan"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="expense", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_expenses_group_id", "group_id"),
        CheckConstraint("total_amount >= 0", name="ck_expenses_total_amount_non_negative"),
    )


class ExpenseAssignment(Base):
    """Maps a receipt item (or a share of it) to a group member within an expense."""
    __tablename__ = "expense_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(), primary_key=True, default=uuid.uuid4
    )
    expense_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("expenses.id", ondelete="CASCADE"),
        nullable=False,
    )
    receipt_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("receipt_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("group_members.id", ondelete="CASCADE"),
        nullable=False,
    )
    # share_quantity allows splitting a single item among multiple members.
    # For example, 2 people sharing 1 pizza: each gets share_quantity = 0.5
    share_quantity: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), default=Decimal("1"), nullable=False
    )

    # Relationships
    expense: Mapped["Expense"] = relationship(back_populates="assignments")
    receipt_item: Mapped["ReceiptItem"] = relationship(back_populates="assignments")
    member: Mapped["GroupMember"] = relationship(back_populates="assignments")

    __table_args__ = (
        Index("ix_expense_assignments_expense_id", "expense_id"),
        Index("ix_expense_assignments_member_id", "member_id"),
        UniqueConstraint("expense_id", "receipt_item_id", "member_id", name="uq_expense_assignments_item_member"),
        CheckConstraint("share_quantity > 0", name="ck_expense_assignments_share_positive"),
    )


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(), primary_key=True, default=uuid.uuid4
    )
    expense_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("expenses.id", ondelete="CASCADE"),
        nullable=False,
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("group_members.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    paypal_order_id: Mapped[str | None] = mapped_column(String(50))
    paypal_capture_id: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status_enum"),
        default=PaymentStatus.PENDING,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    expense: Mapped["Expense"] = relationship(back_populates="payments")
    member: Mapped["GroupMember"] = relationship(back_populates="payments")

    __table_args__ = (
        Index("ix_payments_expense_id", "expense_id"),
        Index("ix_payments_member_id", "member_id"),
        Index("ix_payments_paypal_order_id", "paypal_order_id", unique=True),
        UniqueConstraint("expense_id", "member_id", name="uq_payments_expense_member"),
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
    )
