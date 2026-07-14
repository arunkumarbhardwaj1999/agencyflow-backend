"""Widen OTP storage for email invites

Revision ID: 009_otp_channel
"""

from alembic import op
import sqlalchemy as sa

revision = "009_otp_channel"
down_revision = "008_phone_otp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("phone_otps", "phone", new_column_name="destination", type_=sa.String(255))
    op.add_column(
        "phone_otps",
        sa.Column("channel", sa.String(10), server_default="phone", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("phone_otps", "channel")
    op.alter_column("phone_otps", "destination", new_column_name="phone", type_=sa.String(20))
