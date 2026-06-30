"""GST billing engine + payment integration

Revision ID: 004
Revises: 003
Create Date: 2026-06-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # State codes for GST place-of-supply (CGST+SGST vs IGST)
    op.add_column("companies", sa.Column("state_code", sa.String(2)))
    op.add_column("clients", sa.Column("state_code", sa.String(2)))

    # GST breakdown + payment tracking on invoices
    op.add_column("invoices", sa.Column("cgst", sa.Numeric(12, 2), server_default="0"))
    op.add_column("invoices", sa.Column("sgst", sa.Numeric(12, 2), server_default="0"))
    op.add_column("invoices", sa.Column("igst", sa.Numeric(12, 2), server_default="0"))
    op.add_column("invoices", sa.Column("tax_type", sa.String(20), server_default="igst"))
    op.add_column("invoices", sa.Column("place_of_supply", sa.String(2)))
    op.add_column("invoices", sa.Column("notes", sa.Text()))
    op.add_column("invoices", sa.Column("payment_provider", sa.String(20)))
    op.add_column("invoices", sa.Column("provider_order_id", sa.String(255)))
    op.add_column("invoices", sa.Column("provider_payment_id", sa.String(255)))
    op.add_column("invoices", sa.Column("paid_at", sa.DateTime(timezone=True)))

    op.create_table(
        "invoice_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column(
            "invoice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("invoices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 2), nullable=False, server_default="1"),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
    )
    op.create_index("idx_invoice_items_invoice", "invoice_items", ["invoice_id"])


def downgrade() -> None:
    op.drop_index("idx_invoice_items_invoice", table_name="invoice_items")
    op.drop_table("invoice_items")

    for col in (
        "paid_at",
        "provider_payment_id",
        "provider_order_id",
        "payment_provider",
        "notes",
        "place_of_supply",
        "tax_type",
        "igst",
        "sgst",
        "cgst",
    ):
        op.drop_column("invoices", col)

    op.drop_column("clients", "state_code")
    op.drop_column("companies", "state_code")
