"""Add address column to users for profile / billing contact.

Revision ID: 023_user_address
Revises: 022_client_portal
Create Date: 2026-07-31
"""

from alembic import op
import sqlalchemy as sa

revision = "023_user_address"
down_revision = "022_client_portal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT"))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS address"))
