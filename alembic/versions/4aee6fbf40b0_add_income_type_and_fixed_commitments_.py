"""add income_type and fixed_commitments to users

Revision ID: 4aee6fbf40b0
Revises: ef4b0a4960b8
Create Date: 2026-07-18 15:15:41.805561

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '4aee6fbf40b0'
down_revision: Union[str, None] = 'ef4b0a4960b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


income_type_enum = sa.Enum("salaried", "freelance", "business", "student", name="income_type_enum")


def upgrade() -> None:
    income_type_enum.create(op.get_bind(), checkfirst=True)
    op.add_column("users", sa.Column("income_type", income_type_enum, nullable=True))
    op.add_column("users", sa.Column("fixed_commitments", sa.Numeric(12, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "fixed_commitments")
    op.drop_column("users", "income_type")
    income_type_enum.drop(op.get_bind(), checkfirst=True)
