"""Deal management tables.

Revision ID: 016_deals
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "016_deals"
down_revision = "015_lead_emails"
branch_labels = None
depends_on = None

DEAL_STAGES = ("qualification", "proposal_sent", "negotiation", "won", "lost")


def upgrade() -> None:
    op.create_table(
        "deals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=True),
        sa.Column("client_id", UUID(as_uuid=True), nullable=True),
        sa.Column("assigned_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(255), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(20), nullable=True),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("value", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("probability", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("expected_close_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="qualification"),
        sa.Column("kanban_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("lost_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_deals_company_id", "deals", ["company_id"])
    op.create_index("ix_deals_status", "deals", ["status"])
    op.create_index("ix_deals_lead_id", "deals", ["lead_id"])
    op.create_index("ix_deals_client_id", "deals", ["client_id"])
    op.create_index("ix_deals_pipeline", "deals", ["company_id", "status"])

    op.create_table(
        "deal_timeline",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("deal_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_deal_timeline_deal_id", "deal_timeline", ["deal_id"])
    op.create_index("ix_deal_timeline_company_id", "deal_timeline", ["company_id"])

    op.create_table(
        "deal_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("deal_id", UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_deal_notes_deal_id", "deal_notes", ["deal_id"])

    op.create_table(
        "deal_activities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("deal_id", UUID(as_uuid=True), nullable=False),
        sa.Column("activity_type", sa.String(30), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_completed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("assigned_to_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_deal_activities_deal_id", "deal_activities", ["deal_id"])

    op.create_table(
        "deal_emails",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("deal_id", UUID(as_uuid=True), nullable=False),
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
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sent_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_deal_emails_deal_id", "deal_emails", ["deal_id"])

    op.add_column("documents", sa.Column("deal_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_documents_deal_id", "documents", "deals", ["deal_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_documents_deal_id", "documents", ["deal_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_deal_id", table_name="documents")
    op.drop_constraint("fk_documents_deal_id", "documents", type_="foreignkey")
    op.drop_column("documents", "deal_id")
    op.drop_index("ix_deal_emails_deal_id", table_name="deal_emails")
    op.drop_table("deal_emails")
    op.drop_index("ix_deal_activities_deal_id", table_name="deal_activities")
    op.drop_table("deal_activities")
    op.drop_index("ix_deal_notes_deal_id", table_name="deal_notes")
    op.drop_table("deal_notes")
    op.drop_index("ix_deal_timeline_company_id", table_name="deal_timeline")
    op.drop_index("ix_deal_timeline_deal_id", table_name="deal_timeline")
    op.drop_table("deal_timeline")
    op.drop_index("ix_deals_pipeline", table_name="deals")
    op.drop_index("ix_deals_client_id", table_name="deals")
    op.drop_index("ix_deals_lead_id", table_name="deals")
    op.drop_index("ix_deals_status", table_name="deals")
    op.drop_index("ix_deals_company_id", table_name="deals")
    op.drop_table("deals")
