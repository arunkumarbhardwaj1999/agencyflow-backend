"""Contracts linked to approved proposals.

Revision ID: 019_contracts
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "019_contracts"
down_revision = "018_client_docs_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", UUID(as_uuid=True), nullable=True),
        sa.Column("client_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", UUID(as_uuid=True), nullable=True),
        sa.Column("renewed_from_id", UUID(as_uuid=True), nullable=True),
        sa.Column("contract_number", sa.String(40), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("project_value", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("services", JSONB, server_default="[]", nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), server_default="draft", nullable=False),
        sa.Column("signer_name", sa.String(255), nullable=True),
        sa.Column("signer_email", sa.String(255), nullable=True),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("starts_at", sa.Date(), nullable=True),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("auto_renewal_reminder", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("renewal_reminder_days", sa.Integer(), server_default="30", nullable=False),
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
        sa.ForeignKeyConstraint(["proposal_id"], ["proposals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["renewed_from_id"], ["contracts.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_contracts_company_id", "contracts", ["company_id"])
    op.create_index("ix_contracts_client_id", "contracts", ["client_id"])
    op.create_index("ix_contracts_proposal_id", "contracts", ["proposal_id"])
    op.create_index("ix_contracts_status", "contracts", ["status"])
    op.create_index("ix_contracts_expires_at", "contracts", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_contracts_expires_at", table_name="contracts")
    op.drop_index("ix_contracts_status", table_name="contracts")
    op.drop_index("ix_contracts_proposal_id", table_name="contracts")
    op.drop_index("ix_contracts_client_id", table_name="contracts")
    op.drop_index("ix_contracts_company_id", table_name="contracts")
    op.drop_table("contracts")
