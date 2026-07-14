"""Add lead_emails table for outbound email history.

Revision ID: 015_lead_emails
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "015_lead_emails"
down_revision = "014_lead_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_emails",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("from_email", sa.String(255), nullable=False),
        sa.Column("to_email", sa.String(255), nullable=False),
        sa.Column("delivery_status", sa.String(30), nullable=False, server_default="delivered"),
        sa.Column("open_status", sa.String(30), nullable=False, server_default="unknown"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sent_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_lead_emails_lead_id", "lead_emails", ["lead_id"])
    op.create_index("ix_lead_emails_company_id", "lead_emails", ["company_id"])
    op.create_index("ix_lead_emails_delivery_status", "lead_emails", ["delivery_status"])


def downgrade() -> None:
    op.drop_index("ix_lead_emails_delivery_status", table_name="lead_emails")
    op.drop_index("ix_lead_emails_company_id", table_name="lead_emails")
    op.drop_index("ix_lead_emails_lead_id", table_name="lead_emails")
    op.drop_table("lead_emails")
