"""Allow one analysis to combine multiple completed collection runs.

Revision ID: 20260928_0003
Revises: 20260928_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260928_0003"
down_revision: str | None = "20260928_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs", sa.Column("input_signature", sa.String(64), nullable=True)
    )
    op.execute(
        "UPDATE analysis_runs SET input_signature = "
        "md5(collection_run_id::text) || md5('run:' || collection_run_id::text)"
    )
    op.alter_column("analysis_runs", "input_signature", nullable=False)
    op.drop_constraint(
        "uq_analysis_runs_collection_run_id", "analysis_runs", type_="unique"
    )
    op.create_unique_constraint(
        "uq_analysis_runs_input_signature",
        "analysis_runs",
        ["project_id", "input_signature"],
    )

    op.create_table(
        "analysis_run_collection_runs",
        sa.Column(
            "analysis_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collection_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "analysis_run_id",
            "collection_run_id",
            name="pk_analysis_run_collection_runs",
        ),
        sa.UniqueConstraint(
            "analysis_run_id",
            "position",
            name="uq_analysis_run_collection_position",
        ),
    )
    op.execute(
        "INSERT INTO analysis_run_collection_runs "
        "(analysis_run_id, collection_run_id, position) "
        "SELECT id, collection_run_id, 0 FROM analysis_runs"
    )


def downgrade() -> None:
    op.drop_table("analysis_run_collection_runs")
    op.drop_constraint(
        "uq_analysis_runs_input_signature", "analysis_runs", type_="unique"
    )
    op.create_unique_constraint(
        "uq_analysis_runs_collection_run_id",
        "analysis_runs",
        ["collection_run_id"],
    )
    op.drop_column("analysis_runs", "input_signature")
