"""Allow one idempotent analysis per collection run.

Revision ID: 20260928_0002
Revises: 20260928_0001
Create Date: 2026-09-28
"""

from alembic import op

revision = "20260928_0002"
down_revision = "20260928_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_analysis_runs_collection_run_id",
        "analysis_runs",
        ["collection_run_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_analysis_runs_collection_run_id",
        "analysis_runs",
        type_="unique",
    )
