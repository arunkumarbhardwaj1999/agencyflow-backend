"""Client portal approvals, messages, and project milestones.

Revision ID: 022_client_portal
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "022_client_portal"
down_revision = "021_hr_automations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_milestones",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_project_milestones_company_id", "project_milestones", ["company_id"])
    op.create_index("ix_project_milestones_project_id", "project_milestones", ["project_id"])

    op.create_table(
        "client_approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("document_id", UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("client_comment", sa.Text(), nullable=True),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_client_approvals_company_id", "client_approvals", ["company_id"])
    op.create_index("ix_client_approvals_client_id", "client_approvals", ["client_id"])
    op.create_index("ix_client_approvals_status", "client_approvals", ["status"])

    op.create_table(
        "client_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), nullable=True),
        sa.Column("sender_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("sender_side", sa.String(20), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["sender_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_client_messages_company_id", "client_messages", ["company_id"])
    op.create_index("ix_client_messages_client_id", "client_messages", ["client_id"])
    op.create_index("ix_client_messages_created_at", "client_messages", ["created_at"])


def downgrade() -> None:
    op.drop_table("client_messages")
    op.drop_table("client_approvals")
    op.drop_table("project_milestones")
