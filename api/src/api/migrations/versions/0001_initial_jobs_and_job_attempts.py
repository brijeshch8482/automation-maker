"""Initial schema: jobs and job_attempts.

Revision ID: 0001
Revises:
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# api.db.UTCDateTime stores timestamptz; migrations use the plain type so they never import
# application code that may change later.
TIMESTAMP = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=40), primary_key=True),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("state_changed_at", TIMESTAMP, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("spec", sa.JSON(), nullable=True),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("branch", sa.String(length=120), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("used_custom_step", sa.Boolean(), nullable=True),
        sa.Column("run_url", sa.Text(), nullable=True),
        sa.Column("artifact_key", sa.Text(), nullable=True),
        sa.Column("guide_key", sa.Text(), nullable=True),
        sa.Column("last_report", sa.JSON(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("retry_at", TIMESTAMP, nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
    )
    op.create_index("ix_jobs_state", "jobs", ["state"])
    op.create_index("ix_jobs_user_id", "jobs", ["user_id"])

    op.create_table(
        "job_attempts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(length=40), sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("session_id", sa.String(length=120), nullable=True),
        sa.Column("session_url", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("closed_at", TIMESTAMP, nullable=True),
    )
    op.create_index("ix_job_attempts_job_id", "job_attempts", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_attempts_job_id", table_name="job_attempts")
    op.drop_table("job_attempts")
    op.drop_index("ix_jobs_user_id", table_name="jobs")
    op.drop_index("ix_jobs_state", table_name="jobs")
    op.drop_table("jobs")
