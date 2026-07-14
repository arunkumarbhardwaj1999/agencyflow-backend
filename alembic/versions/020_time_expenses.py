"""Time tracking and project expenses.

Revision ID: 020_time_expenses
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "020_time_expenses"
down_revision = "019_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("estimated_hours", sa.Numeric(10, 2), server_default="0", nullable=False),
    )

    op.create_table(
        "time_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("is_running", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_time_entries_company_id", "time_entries", ["company_id"])
    op.create_index("ix_time_entries_user_id", "time_entries", ["user_id"])
    op.create_index("ix_time_entries_project_id", "time_entries", ["project_id"])
    op.create_index("ix_time_entries_task_id", "time_entries", ["task_id"])
    op.create_index("ix_time_entries_is_running", "time_entries", ["is_running"])

    op.create_table(
        "project_expenses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_project_expenses_company_id", "project_expenses", ["company_id"])
    op.create_index("ix_project_expenses_project_id", "project_expenses", ["project_id"])
    op.create_index("ix_project_expenses_category", "project_expenses", ["category"])


def downgrade() -> None:
    op.drop_index("ix_project_expenses_category", table_name="project_expenses")
    op.drop_index("ix_project_expenses_project_id", table_name="project_expenses")
    op.drop_index("ix_project_expenses_company_id", table_name="project_expenses")
    op.drop_table("project_expenses")
    op.drop_index("ix_time_entries_is_running", table_name="time_entries")
    op.drop_index("ix_time_entries_task_id", table_name="time_entries")
    op.drop_index("ix_time_entries_project_id", table_name="time_entries")
    op.drop_index("ix_time_entries_user_id", table_name="time_entries")
    op.drop_index("ix_time_entries_company_id", table_name="time_entries")
    op.drop_table("time_entries")
    op.drop_column("projects", "estimated_hours")
