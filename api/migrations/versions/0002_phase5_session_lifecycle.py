"""Add Phase 5 session lifecycle fields.

Revision ID: 0002_phase5
Revises: 0001_phase2_4_6
Create Date: 2026-11-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_phase5"
down_revision: Union[str, None] = "0001_phase2_4_6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lab_sessions",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "lab_sessions",
        sa.Column("extension_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("lab_sessions", "extension_count")
    op.drop_column("lab_sessions", "last_activity_at")
