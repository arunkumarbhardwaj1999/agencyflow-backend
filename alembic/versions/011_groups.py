"""Add groups and group members tables.

Revision ID: 011_groups
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "011_groups"
down_revision = "010_user_invited_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "groups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("company_id", "name", name="uq_group_company_name"),
    )
    op.create_index("ix_groups_company_id", "groups", ["company_id"])

    op.create_table(
        "group_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("group_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_member"),
    )
    op.create_index("ix_group_members_group_id", "group_members", ["group_id"])
    op.create_index("ix_group_members_user_id", "group_members", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_group_members_user_id", table_name="group_members")
    op.drop_index("ix_group_members_group_id", table_name="group_members")
    op.drop_table("group_members")
    op.drop_index("ix_groups_company_id", table_name="groups")
    op.drop_table("groups")
