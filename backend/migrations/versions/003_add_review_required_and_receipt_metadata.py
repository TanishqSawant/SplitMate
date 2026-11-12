"""Add review_required status, receipt metadata fields, and nullable receipt item columns.

Revision ID: 003_add_review_required_and_receipt_metadata
Revises: 002_add_users_and_auth
Create Date: 2026-11-10 18:00:00.000000

Changes:
  receipts:
    - currency: NOT NULL DEFAULT 'USD'  â†’  NULL (no default; unknown currency stays None)
    - ADD missing_fields TEXT NULL
    - ADD uncertain_fields TEXT NULL
    - ADD warnings TEXT NULL
    - ADD confidence FLOAT NULL
    - ADD error_code VARCHAR(64) NULL
    - ADD error_message TEXT NULL
    - ADD is_user_reviewed BOOLEAN NOT NULL DEFAULT FALSE
    - extraction_status enum: add 'review_required' value
  receipt_items:
    - quantity: INTEGER NOT NULL â†’ NUMERIC(10,4) NULL
    - unit_price: NUMERIC(12,2) NOT NULL â†’ NUMERIC(12,2) NULL
    - total_price: NUMERIC(12,2) NOT NULL â†’ NUMERIC(12,2) NULL
    - check constraints updated to allow NULL

Safe downgrade: refuses if incompatible data exists rather than silently destroying it.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_add_review_required_and_receipt_metadata"
down_revision: Union[str, None] = "002_add_users_and_auth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgresql() -> bool:
    return op.get_context().dialect.name == "postgresql"


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    dialect = op.get_context().dialect.name

    # --- 1. Add review_required to extraction_status enum ---
    if dialect == "postgresql":
        # PostgreSQL enum ALTER must run outside any transaction block.
        with op.get_context().autocommit_block():
            op.execute(
                "ALTER TYPE extraction_status_enum ADD VALUE IF NOT EXISTS 'review_required'"
            )
    # SQLite: the CHECK constraint is recreated via batch_alter_table below.

    # --- 2. Update receipts table ---
    with op.batch_alter_table("receipts", schema=None) as batch_op:
        # Make currency nullable (drop default + NOT NULL)
        batch_op.alter_column(
            "currency",
            existing_type=sa.String(length=3),
            nullable=True,
            server_default=None,
        )
        # Add metadata columns
        batch_op.add_column(sa.Column("document_type", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("missing_fields", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("uncertain_fields", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("warnings", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("error_code", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("error_message", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "is_user_reviewed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),  # SQLite FALSE; PostgreSQL accepts '0'
            )
        )

        # On SQLite, batch_alter_table will recreate the table, which also regenerates
        # the CHECK constraint from the new Enum definition (review_required included).
        if dialect == "postgresql":
            # Alter extraction_status column to use updated enum type
            batch_op.alter_column(
                "extraction_status",
                existing_type=sa.Enum(
                    "pending", "processing", "completed", "failed",
                    name="extraction_status_enum",
                ),
                type_=sa.Enum(
                    "pending", "processing", "completed", "review_required", "failed",
                    name="extraction_status_enum",
                ),
                existing_nullable=False,
            )

    # --- 3. Update receipt_items table ---
    with op.batch_alter_table("receipt_items", schema=None) as batch_op:
        # Drop old non-nullable check constraints (renamed below for clarity)
        # Note: batch_alter_table on SQLite recreates the table with new constraints.
        if dialect == "postgresql":
            batch_op.drop_constraint("ck_receipt_items_quantity_positive", type_="check")
            batch_op.drop_constraint("ck_receipt_items_unit_price_non_negative", type_="check")
            batch_op.drop_constraint("ck_receipt_items_total_price_non_negative", type_="check")

        # quantity: INTEGER NOT NULL â†’ NUMERIC(10,4) NULL
        batch_op.alter_column(
            "quantity",
            existing_type=sa.Integer(),
            type_=sa.Numeric(10, 4),
            nullable=True,
        )
        # unit_price: NUMERIC(12,2) NOT NULL â†’ NULL
        batch_op.alter_column(
            "unit_price",
            existing_type=sa.Numeric(precision=12, scale=2),
            nullable=True,
        )
        # total_price: NUMERIC(12,2) NOT NULL â†’ NULL
        batch_op.alter_column(
            "total_price",
            existing_type=sa.Numeric(precision=12, scale=2),
            nullable=True,
        )

        # Re-add check constraints that allow NULL
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


# ---------------------------------------------------------------------------
# Downgrade â€” refuses if incompatible data exists
# ---------------------------------------------------------------------------

def downgrade() -> None:
    dialect = op.get_context().dialect.name

    # Safety checks â€” refuse if data would be silently destroyed
    conn = op.get_bind()

    # 1. Any receipt_items with fractional quantities?
    if dialect == "postgresql":
        frac_qty = conn.execute(
            sa.text("SELECT COUNT(*) FROM receipt_items WHERE quantity IS NULL OR quantity != TRUNC(quantity)")
        ).scalar()
    else:
        frac_qty = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM receipt_items "
                "WHERE quantity IS NULL OR (quantity % 1.0) != 0.0"
            )
        ).scalar()

    if frac_qty and frac_qty > 0:
        raise RuntimeError(
            f"Cannot safely downgrade: {frac_qty} receipt_items row(s) have NULL or fractional "
            "quantity values that cannot be represented as INTEGER NOT NULL."
        )

    # 2. Any receipt_items with NULL unit_price or total_price?
    null_prices = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM receipt_items "
            "WHERE unit_price IS NULL OR total_price IS NULL"
        )
    ).scalar()
    if null_prices and null_prices > 0:
        raise RuntimeError(
            f"Cannot safely downgrade: {null_prices} receipt_items row(s) have NULL price fields "
            "that cannot be represented as NUMERIC NOT NULL."
        )

    # 3. Any receipts in review_required status?
    review_count = conn.execute(
        sa.text("SELECT COUNT(*) FROM receipts WHERE extraction_status = 'review_required'")
    ).scalar()
    if review_count and review_count > 0:
        raise RuntimeError(
            f"Cannot safely downgrade: {review_count} receipt(s) are in 'review_required' status "
            "which does not exist in the previous schema."
        )

    # --- Revert receipt_items ---
    with op.batch_alter_table("receipt_items", schema=None) as batch_op:
        batch_op.drop_constraint("ck_receipt_items_quantity_positive", type_="check")
        batch_op.drop_constraint("ck_receipt_items_unit_price_non_negative", type_="check")
        batch_op.drop_constraint("ck_receipt_items_total_price_non_negative", type_="check")

        batch_op.alter_column(
            "quantity",
            existing_type=sa.Numeric(10, 4),
            type_=sa.Integer(),
            nullable=False,
        )
        batch_op.alter_column(
            "unit_price",
            existing_type=sa.Numeric(precision=12, scale=2),
            nullable=False,
        )
        batch_op.alter_column(
            "total_price",
            existing_type=sa.Numeric(precision=12, scale=2),
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

    # --- Revert receipts ---
    with op.batch_alter_table("receipts", schema=None) as batch_op:
        batch_op.drop_column("is_user_reviewed")
        batch_op.drop_column("error_message")
        batch_op.drop_column("error_code")
        batch_op.drop_column("confidence")
        batch_op.drop_column("warnings")
        batch_op.drop_column("uncertain_fields")
        batch_op.drop_column("missing_fields")
        batch_op.drop_column("document_type")

        # Restore currency as NOT NULL DEFAULT 'USD'
        # First fill any NULLs that may have been introduced
        conn.execute(
            sa.text("UPDATE receipts SET currency = 'USD' WHERE currency IS NULL")
        )
        batch_op.alter_column(
            "currency",
            existing_type=sa.String(length=3),
            nullable=False,
            server_default="USD",
        )

    # PostgreSQL: cannot remove an enum value â€” the enum is left as-is.
    # This is documented PostgreSQL behaviour: ALTER TYPE ... DROP VALUE is not supported.
