"""Initial schema: expense_groups, group_members, receipts, receipt_items, expenses, expense_assignments, payments

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-11-07 17:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Enums
    extraction_status_enum = postgresql.ENUM(
        "pending", "processing", "completed", "failed", name="extraction_status_enum"
    )
    payment_status_enum = postgresql.ENUM(
        "pending", "order_created", "captured", "failed", name="payment_status_enum"
    )
    extraction_status_enum.create(op.get_bind(), checkfirst=True)
    payment_status_enum.create(op.get_bind(), checkfirst=True)

    # 2. expense_groups
    op.create_table(
        "expense_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 3. group_members
    op.create_table(
        "group_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("expense_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_group_members_group_id", "group_members", ["group_id"])
    op.create_index("ix_group_members_email", "group_members", ["email"])

    # 4. receipts
    op.create_table(
        "receipts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_file_path", sa.Text(), nullable=False),
        sa.Column("merchant_name", sa.String(length=255), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("tax", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "extraction_status",
            postgresql.ENUM(
                "pending", "processing", "completed", "failed",
                name="extraction_status_enum",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 5. receipt_items
    op.create_table(
        "receipt_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "receipt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receipts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("item_name", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("total_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_receipt_items_quantity_positive"),
        sa.CheckConstraint(
            "unit_price >= 0", name="ck_receipt_items_unit_price_non_negative"
        ),
        sa.CheckConstraint(
            "total_price >= 0", name="ck_receipt_items_total_price_non_negative"
        ),
    )
    op.create_index("ix_receipt_items_receipt_id", "receipt_items", ["receipt_id"])

    # 6. expenses
    op.create_table(
        "expenses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "group_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("expense_groups.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "receipt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receipts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "total_amount >= 0", name="ck_expenses_total_amount_non_negative"
        ),
    )
    op.create_index("ix_expenses_group_id", "expenses", ["group_id"])

    # 7. expense_assignments
    op.create_table(
        "expense_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "expense_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("expenses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "receipt_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receipt_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("group_members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "share_quantity",
            sa.Numeric(precision=10, scale=4),
            server_default="1",
            nullable=False,
        ),
        sa.CheckConstraint(
            "share_quantity > 0", name="ck_expense_assignments_share_positive"
        ),
        sa.UniqueConstraint(
            "expense_id", "receipt_item_id", "member_id", name="uq_expense_assignments_item_member"
        ),
    )
    op.create_index(
        "ix_expense_assignments_expense_id", "expense_assignments", ["expense_id"]
    )
    op.create_index(
        "ix_expense_assignments_member_id", "expense_assignments", ["member_id"]
    )

    # 8. payments
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "expense_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("expenses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "member_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("group_members.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("paypal_order_id", sa.String(length=50), nullable=True),
        sa.Column("paypal_capture_id", sa.String(length=50), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending", "order_created", "captured", "failed",
                name="payment_status_enum",
                create_type=False,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sa.UniqueConstraint("expense_id", "member_id", name="uq_payments_expense_member"),
    )
    op.create_index("ix_payments_expense_id", "payments", ["expense_id"])
    op.create_index("ix_payments_member_id", "payments", ["member_id"])
    op.create_index(
        "ix_payments_paypal_order_id", "payments", ["paypal_order_id"], unique=True
    )


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("expense_assignments")
    op.drop_table("expenses")
    op.drop_table("receipt_items")
    op.drop_table("receipts")
    op.drop_table("group_members")
    op.drop_table("expense_groups")
    sa.Enum(name="payment_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="extraction_status_enum").drop(op.get_bind(), checkfirst=True)
