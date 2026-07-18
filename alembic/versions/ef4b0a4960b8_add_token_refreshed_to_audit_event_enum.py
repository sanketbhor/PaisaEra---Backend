"""add token_refreshed to audit_event_enum

Revision ID: ef4b0a4960b8
Revises: 2b0923ee139b
Create Date: 2026-07-18 15:00:34.288996

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ef4b0a4960b8'
down_revision: Union[str, None] = '2b0923ee139b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_event_enum ADD VALUE IF NOT EXISTS 'token_refreshed'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE; removing an enum value
    # requires rebuilding the type. Left as a no-op — the extra value is
    # harmless if this migration is rolled back.
    pass
