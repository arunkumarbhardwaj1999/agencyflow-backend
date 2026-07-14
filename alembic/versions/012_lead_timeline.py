"""Lead activity timeline + lead attachments on documents.

Revision ID: 012_lead_timeline
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "012_lead_timeline"
down_revision = "011_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_timeline",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_lead_timeline_lead_id", "lead_timeline", ["lead_id"])
    op.create_index("ix_lead_timeline_company_id", "lead_timeline", ["company_id"])
    op.create_index("ix_lead_timeline_event_type", "lead_timeline", ["event_type"])
    op.create_index("ix_lead_timeline_created_at", "lead_timeline", ["created_at"])

    op.add_column("documents", sa.Column("lead_id", UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_documents_lead_id",
        "documents",
        "leads",
        ["lead_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_documents_lead_id", "documents", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_documents_lead_id", table_name="documents")
    op.drop_constraint("fk_documents_lead_id", "documents", type_="foreignkey")
    op.drop_column("documents", "lead_id")

    op.drop_index("ix_lead_timeline_created_at", table_name="lead_timeline")
    op.drop_index("ix_lead_timeline_event_type", table_name="lead_timeline")
    op.drop_index("ix_lead_timeline_company_id", table_name="lead_timeline")
    op.drop_index("ix_lead_timeline_lead_id", table_name="lead_timeline")
    op.drop_table("lead_timeline")
