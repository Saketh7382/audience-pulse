"""Track cumulative Pulse baselines and newly added collection runs.

Revision ID: 20260928_0004
Revises: 20260928_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260928_0004"
down_revision: str | None = "20260928_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column(
            "baseline_analysis_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_analysis_runs_baseline",
        "analysis_runs",
        "analysis_runs",
        ["baseline_analysis_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_analysis_runs_baseline",
        "analysis_runs",
        ["baseline_analysis_run_id"],
    )
    op.add_column(
        "analysis_run_collection_runs",
        sa.Column(
            "is_incremental",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column(
        "analysis_run_collection_runs",
        "is_incremental",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("analysis_run_collection_runs", "is_incremental")
    op.drop_index("ix_analysis_runs_baseline", table_name="analysis_runs")
    op.drop_constraint("fk_analysis_runs_baseline", "analysis_runs", type_="foreignkey")
    op.drop_column("analysis_runs", "baseline_analysis_run_id")
