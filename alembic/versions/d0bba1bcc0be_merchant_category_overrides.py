"""merchant category overrides

Revision ID: d0bba1bcc0be
Revises: 4aee6fbf40b0
Create Date: 2026-07-20 13:54:42.422516

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd0bba1bcc0be'
down_revision: Union[str, None] = '4aee6fbf40b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "merchant_category_overrides",
        sa.Column("id", sa.dialects.postgresql.UUID(), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("merchant_name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("source", sa.Enum("ai", "user", name="override_source_enum"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "merchant_name", name="uq_override_user_merchant"),
    )


def downgrade() -> None:
    op.drop_table("merchant_category_overrides")
    sa.Enum(name="override_source_enum").drop(op.get_bind(), checkfirst=True)
