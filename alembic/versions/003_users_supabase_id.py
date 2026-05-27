"""Add supabase_user_id to users

Revision ID: 003
Revises: 002
Create Date: 2026-05-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("supabase_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("idx_users_supabase_user_id", "users", ["supabase_user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("idx_users_supabase_user_id", table_name="users")
    op.drop_column("users", "supabase_user_id")
