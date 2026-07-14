"""Add username and must_change_password to users

Revision ID: 007
Revises: 006
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(50), nullable=True))
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    # Backfill username from email local-part for existing accounts.
    op.execute(
        """
        UPDATE users
        SET username = LOWER(REGEXP_REPLACE(SPLIT_PART(email, '@', 1), '[^a-z0-9_]', '', 'g'))
        WHERE username IS NULL
        """
    )
    op.execute(
        """
        UPDATE users u
        SET username = u.username || '_' || SUBSTRING(REPLACE(u.id::text, '-', ''), 1, 6)
        WHERE u.id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY username ORDER BY created_at) AS rn
                FROM users
            ) t WHERE t.rn > 1
        )
        """
    )
    op.execute(
        """
        UPDATE users
        SET username = 'user_' || SUBSTRING(REPLACE(id::text, '-', ''), 1, 8)
        WHERE username IS NULL OR username = ''
        """
    )

    op.alter_column("users", "username", nullable=False)
    op.create_index("ix_users_username", "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_username", table_name="users")
    op.drop_column("users", "must_change_password")
    op.drop_column("users", "username")
