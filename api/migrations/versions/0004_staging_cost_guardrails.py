"""Track the start of billable lab VM sessions.

Revision ID: 0004_staging_cost_guardrails
Revises: 0003
Create Date: 2026-11-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_staging_cost_guardrails"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "lab_sessions",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_lab_sessions_started_at", "lab_sessions", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_lab_sessions_started_at", table_name="lab_sessions")
    op.drop_column("lab_sessions", "started_at")
