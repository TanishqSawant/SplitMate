"""Add users table and ownership foreign keys for auth and IDOR protection.

Revision ID: 002_add_users_and_auth
Revises: 001_initial_schema
Create Date: 2026-11-10 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "002_add_users_and_auth"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create users table
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
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
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # 2. Add creator_id to expense_groups
    op.add_column(
        "expense_groups",
        sa.Column("creator_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_expense_groups_creator_id_users",
        "expense_groups",
        "users",
        ["creator_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_expense_groups_creator_id", "expense_groups", ["creator_id"])

    # 3. Add user_id to group_members
    op.add_column(
        "group_members",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_group_members_user_id_users",
        "group_members",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_group_members_user_id", "group_members", ["user_id"])

    # 4. Add uploader_id to receipts
    op.add_column(
        "receipts",
        sa.Column("uploader_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_receipts_uploader_id_users",
        "receipts",
        "users",
        ["uploader_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_receipts_uploader_id", "receipts", ["uploader_id"])


def downgrade() -> None:
    # 4. Remove uploader_id from receipts
    op.drop_index("ix_receipts_uploader_id", table_name="receipts")
    op.drop_constraint("fk_receipts_uploader_id_users", "receipts", type_="foreignkey")
    op.drop_column("receipts", "uploader_id")

    # 3. Remove user_id from group_members
    op.drop_index("ix_group_members_user_id", table_name="group_members")
    op.drop_constraint("fk_group_members_user_id_users", "group_members", type_="foreignkey")
    op.drop_column("group_members", "user_id")

    # 2. Remove creator_id from expense_groups
    op.drop_index("ix_expense_groups_creator_id", table_name="expense_groups")
    op.drop_constraint("fk_expense_groups_creator_id_users", "expense_groups", type_="foreignkey")
    op.drop_column("expense_groups", "creator_id")

    # 1. Drop users table
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

