"""Communication center tables.

Revision ID: 017_communications
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "017_communications"
down_revision = "016_deals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "internal_comments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=True),
        sa.Column("deal_id", UUID(as_uuid=True), nullable=True),
        sa.Column("client_id", UUID(as_uuid=True), nullable=True),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("invoice_id", UUID(as_uuid=True), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_internal_comments_company_id", "internal_comments", ["company_id"])

    op.create_table(
        "sms_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=True),
        sa.Column("deal_id", UUID(as_uuid=True), nullable=True),
        sa.Column("client_id", UUID(as_uuid=True), nullable=True),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="delivered"),
        sa.Column("read_status", sa.String(30), nullable=False, server_default="unknown"),
        sa.Column("sent_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("is_proxy_for_whatsapp", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sent_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_sms_logs_company_id", "sms_logs", ["company_id"])

    op.create_table(
        "inbox_read_marks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("item_key", sa.String(120), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "item_key", name="uq_inbox_read_user_item"),
    )
    op.create_index("ix_inbox_read_marks_user_id", "inbox_read_marks", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_inbox_read_marks_user_id", table_name="inbox_read_marks")
    op.drop_table("inbox_read_marks")
    op.drop_index("ix_sms_logs_company_id", table_name="sms_logs")
    op.drop_table("sms_logs")
    op.drop_index("ix_internal_comments_company_id", table_name="internal_comments")
    op.drop_table("internal_comments")
