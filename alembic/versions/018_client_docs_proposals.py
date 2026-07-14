"""Client document folders and proposals.

Revision ID: 018_client_docs_proposals
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "018_client_docs_proposals"
down_revision = "017_communications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("client_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("folder", sa.String(50), server_default="others", nullable=False),
    )
    op.create_foreign_key(
        "fk_documents_client_id",
        "documents",
        "clients",
        ["client_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_documents_client_id", "documents", ["client_id"])

    op.create_table(
        "proposals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=True),
        sa.Column("deal_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("template_key", sa.String(30), server_default="website", nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("project_value", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("services", JSONB, server_default="[]", nullable=False),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("timeline", sa.Text(), nullable=True),
        sa.Column("deliverables", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("pricing", sa.Text(), nullable=True),
        sa.Column("terms", sa.Text(), nullable=True),
        sa.Column("conclusion", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), server_default="draft", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_proposals_company_id", "proposals", ["company_id"])
    op.create_index("ix_proposals_client_id", "proposals", ["client_id"])
    op.create_index("ix_proposals_status", "proposals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_proposals_status", table_name="proposals")
    op.drop_index("ix_proposals_client_id", table_name="proposals")
    op.drop_index("ix_proposals_company_id", table_name="proposals")
    op.drop_table("proposals")
    op.drop_index("ix_documents_client_id", table_name="documents")
    op.drop_constraint("fk_documents_client_id", "documents", type_="foreignkey")
    op.drop_column("documents", "folder")
    op.drop_column("documents", "client_id")
