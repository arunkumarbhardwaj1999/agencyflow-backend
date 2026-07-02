"""WhatsApp template_key column

Revision ID: 006
Revises: 005
Create Date: 2026-07-02
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("whatsapp_logs", sa.Column("template_key", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("whatsapp_logs", "template_key")
