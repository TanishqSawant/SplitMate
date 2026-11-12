"""Make receipt items quantity fractional (Numeric) and nullable, prices nullable, and add review_required status

Revision ID: 002_receipt_item_fractional_and_nullable
Revises: 001_initial_schema
Create Date: 2026-11-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "002_receipt_item_fractional_and_nullable"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add 'review_required' to extraction_status_enum if PostgreSQL
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE extraction_status_enum ADD VALUE IF NOT EXISTS 'review_required'")

    # 2. receipts.currency: make nullable
    with op.batch_alter_table("receipts") as batch_op:
        batch_op.alter_column(
            "currency",
            existing_type=sa.String(length=3),
            nullable=True,
            server_default=None,
        )

    # 3. receipt_items:
    # - quantity: Numeric(10, 4), nullable=True
    # - unit_price: Numeric(12, 2), nullable=True
    # - total_price: Numeric(12, 2), nullable=True
    # - check constraints updated to allow null
    with op.batch_alter_table("receipt_items") as batch_op:
        batch_op.drop_constraint("ck_receipt_items_quantity_positive", type_="check")
        batch_op.drop_constraint("ck_receipt_items_unit_price_non_negative", type_="check")
        batch_op.drop_constraint("ck_receipt_items_total_price_non_negative", type_="check")

        batch_op.alter_column(
            "quantity",
            existing_type=sa.Integer(),
            type_=sa.Numeric(precision=10, scale=4),
            nullable=True,
            server_default=None,
        )
        batch_op.alter_column(
            "unit_price",
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.Numeric(precision=12, scale=2),
            nullable=True,
        )
        batch_op.alter_column(
            "total_price",
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.Numeric(precision=12, scale=2),
            nullable=True,
        )

        batch_op.create_check_constraint(
            "ck_receipt_items_quantity_positive",
            "quantity IS NULL OR quantity > 0",
        )
        batch_op.create_check_constraint(
            "ck_receipt_items_unit_price_non_negative",
            "unit_price IS NULL OR unit_price >= 0",
        )
        batch_op.create_check_constraint(
            "ck_receipt_items_total_price_non_negative",
            "total_price IS NULL OR total_price >= 0",
        )


def downgrade() -> None:
    # 1. Fill nulls before restoring NOT NULL constraints
    op.execute("UPDATE receipt_items SET quantity = 1 WHERE quantity IS NULL")
    op.execute("UPDATE receipt_items SET unit_price = 0 WHERE unit_price IS NULL")
    op.execute("UPDATE receipt_items SET total_price = 0 WHERE total_price IS NULL")

    # 2. Revert receipt_items columns and constraints
    with op.batch_alter_table("receipt_items") as batch_op:
        batch_op.drop_constraint("ck_receipt_items_quantity_positive", type_="check")
        batch_op.drop_constraint("ck_receipt_items_unit_price_non_negative", type_="check")
        batch_op.drop_constraint("ck_receipt_items_total_price_non_negative", type_="check")

        batch_op.alter_column(
            "quantity",
            existing_type=sa.Numeric(precision=10, scale=4),
            type_=sa.Integer(),
            nullable=False,
            server_default="1",
        )
        batch_op.alter_column(
            "unit_price",
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.Numeric(precision=12, scale=2),
            nullable=False,
        )
        batch_op.alter_column(
            "total_price",
            existing_type=sa.Numeric(precision=12, scale=2),
            type_=sa.Numeric(precision=12, scale=2),
            nullable=False,
        )

        batch_op.create_check_constraint(
            "ck_receipt_items_quantity_positive",
            "quantity > 0",
        )
        batch_op.create_check_constraint(
            "ck_receipt_items_unit_price_non_negative",
            "unit_price >= 0",
        )
        batch_op.create_check_constraint(
            "ck_receipt_items_total_price_non_negative",
            "total_price >= 0",
        )

    # 3. Revert receipts.currency and extraction_status
    op.execute("UPDATE receipts SET currency = 'USD' WHERE currency IS NULL")
    op.execute("UPDATE receipts SET extraction_status = 'pending' WHERE extraction_status = 'review_required'")

    with op.batch_alter_table("receipts") as batch_op:
        batch_op.alter_column(
            "currency",
            existing_type=sa.String(length=3),
            nullable=False,
            server_default="USD",
        )

