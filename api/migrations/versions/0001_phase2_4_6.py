"""Add lab sessions and learner progress.

Revision ID: 0001_phase2_4_6
Revises:
Create Date: 2026-11-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_phase2_4_6"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lab_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("lab_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("vm_name", sa.String(length=128), nullable=True),
        sa.Column("resource_group", sa.String(length=128), nullable=True),
        sa.Column("vm_private_ip", sa.String(length=45), nullable=True),
        sa.Column("vm_username", sa.String(length=128), nullable=True),
        sa.Column("vm_password_secret_name", sa.String(length=128), nullable=True),
        sa.Column("azure_username_secret_name", sa.String(length=128), nullable=True),
        sa.Column("azure_password_secret_name", sa.String(length=128), nullable=True),
        sa.Column("azure_resource_group", sa.String(length=128), nullable=True),
        sa.Column("azure_subscription_id", sa.String(length=36), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_lab_sessions_user_id", "lab_sessions", ["user_id"])
    op.create_index("ix_lab_sessions_lab_id", "lab_sessions", ["lab_id"])
    op.create_table(
        "lab_progress",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("lab_id", sa.String(length=128), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "lab_id", name="uq_lab_progress_user_lab"),
    )
    op.create_index("ix_lab_progress_user_id", "lab_progress", ["user_id"])
    op.create_index("ix_lab_progress_lab_id", "lab_progress", ["lab_id"])
    op.create_table(
        "task_progress",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("lab_id", sa.String(length=128), nullable=False),
        sa.Column("task_index", sa.Integer(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id", "lab_id", "task_index", name="uq_task_progress_user_lab_task"
        ),
    )
    op.create_index("ix_task_progress_user_id", "task_progress", ["user_id"])
    op.create_index("ix_task_progress_lab_id", "task_progress", ["lab_id"])


def downgrade() -> None:
    op.drop_index("ix_task_progress_lab_id", table_name="task_progress")
    op.drop_index("ix_task_progress_user_id", table_name="task_progress")
    op.drop_table("task_progress")
    op.drop_index("ix_lab_progress_lab_id", table_name="lab_progress")
    op.drop_index("ix_lab_progress_user_id", table_name="lab_progress")
    op.drop_table("lab_progress")
    op.drop_index("ix_lab_sessions_lab_id", table_name="lab_sessions")
    op.drop_index("ix_lab_sessions_user_id", table_name="lab_sessions")
    op.drop_table("lab_sessions")
