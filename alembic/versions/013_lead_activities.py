"""Add lead activities table for salesperson activity history.

Revision ID: 013_lead_activities
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "013_lead_activities"
down_revision = "012_lead_timeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lead_activities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), nullable=False),
        sa.Column("activity_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("assigned_to_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_lead_activities_lead_id", "lead_activities", ["lead_id"])
    op.create_index("ix_lead_activities_company_id", "lead_activities", ["company_id"])
    op.create_index("ix_lead_activities_activity_type", "lead_activities", ["activity_type"])
    op.create_index("ix_lead_activities_scheduled_at", "lead_activities", ["scheduled_at"])
    op.create_index("ix_lead_activities_completed_at", "lead_activities", ["completed_at"])
    op.create_index("ix_lead_activities_is_completed", "lead_activities", ["is_completed"])


def downgrade() -> None:
    op.drop_index("ix_lead_activities_is_completed", table_name="lead_activities")
    op.drop_index("ix_lead_activities_completed_at", table_name="lead_activities")
    op.drop_index("ix_lead_activities_scheduled_at", table_name="lead_activities")
    op.drop_index("ix_lead_activities_activity_type", table_name="lead_activities")
    op.drop_index("ix_lead_activities_company_id", table_name="lead_activities")
    op.drop_index("ix_lead_activities_lead_id", table_name="lead_activities")
    op.drop_table("lead_activities")
