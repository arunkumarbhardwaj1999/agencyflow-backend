"""HR module and workflow automations.

Revision ID: 021_hr_automations
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "021_hr_automations"
down_revision = "020_time_expenses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "employee_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("department", sa.String(100), nullable=True),
        sa.Column("designation", sa.String(100), nullable=True),
        sa.Column("joining_date", sa.Date(), nullable=True),
        sa.Column("salary", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("annual_leave_balance", sa.Integer(), server_default="12", nullable=False),
        sa.Column("casual_leave_balance", sa.Integer(), server_default="6", nullable=False),
        sa.Column("medical_leave_balance", sa.Integer(), server_default="6", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_employee_profiles_user_id"),
    )
    op.create_index("ix_employee_profiles_company_id", "employee_profiles", ["company_id"])

    op.create_table(
        "attendance_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("check_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(30), server_default="present", nullable=False),
        sa.Column("work_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "work_date", name="uq_attendance_user_date"),
    )
    op.create_index("ix_attendance_logs_company_id", "attendance_logs", ["company_id"])
    op.create_index("ix_attendance_logs_user_id", "attendance_logs", ["user_id"])
    op.create_index("ix_attendance_logs_work_date", "attendance_logs", ["work_date"])

    op.create_table(
        "leave_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("leave_type", sa.String(30), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("days", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("reviewed_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_leave_requests_company_id", "leave_requests", ["company_id"])
    op.create_index("ix_leave_requests_user_id", "leave_requests", ["user_id"])
    op.create_index("ix_leave_requests_status", "leave_requests", ["status"])

    op.create_table(
        "company_holidays",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("is_optional", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_company_holidays_company_id", "company_holidays", ["company_id"])
    op.create_index("ix_company_holidays_holiday_date", "company_holidays", ["holiday_date"])

    op.create_table(
        "automations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("trigger_key", sa.String(50), nullable=False),
        sa.Column("actions", JSONB, server_default="[]", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_automations_company_id", "automations", ["company_id"])
    op.create_index("ix_automations_trigger_key", "automations", ["trigger_key"])

    op.create_table(
        "automation_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("automation_id", UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_key", sa.String(50), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(30), server_default="completed", nullable=False),
        sa.Column("result", JSONB, server_default="{}", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_automation_runs_company_id", "automation_runs", ["company_id"])
    op.create_index("ix_automation_runs_automation_id", "automation_runs", ["automation_id"])


def downgrade() -> None:
    op.drop_index("ix_automation_runs_automation_id", table_name="automation_runs")
    op.drop_index("ix_automation_runs_company_id", table_name="automation_runs")
    op.drop_table("automation_runs")
    op.drop_index("ix_automations_trigger_key", table_name="automations")
    op.drop_index("ix_automations_company_id", table_name="automations")
    op.drop_table("automations")
    op.drop_index("ix_company_holidays_holiday_date", table_name="company_holidays")
    op.drop_index("ix_company_holidays_company_id", table_name="company_holidays")
    op.drop_table("company_holidays")
    op.drop_index("ix_leave_requests_status", table_name="leave_requests")
    op.drop_index("ix_leave_requests_user_id", table_name="leave_requests")
    op.drop_index("ix_leave_requests_company_id", table_name="leave_requests")
    op.drop_table("leave_requests")
    op.drop_index("ix_attendance_logs_work_date", table_name="attendance_logs")
    op.drop_index("ix_attendance_logs_user_id", table_name="attendance_logs")
    op.drop_index("ix_attendance_logs_company_id", table_name="attendance_logs")
    op.drop_table("attendance_logs")
    op.drop_index("ix_employee_profiles_company_id", table_name="employee_profiles")
    op.drop_table("employee_profiles")
