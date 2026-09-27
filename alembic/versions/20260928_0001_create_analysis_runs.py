"""Create file-backed analysis run metadata.

Revision ID: 20260928_0001
Revises:
Create Date: 2026-09-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260928_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "collection_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column(
            "current_stage",
            sa.String(100),
            nullable=False,
            server_default="INITIALIZING",
        ),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "storage_backend", sa.String(32), nullable=False, server_default="local"
        ),
        sa.Column("manifest_path", sa.String(1000), nullable=False),
        sa.Column("final_result_path", sa.String(1000), nullable=True),
        sa.Column("executive_report_path", sa.String(1000), nullable=True),
        sa.Column("analyzer_version", sa.String(100), nullable=False),
        sa.Column("prompt_bundle_version", sa.String(100), nullable=False),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "processed_mention_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "model_usage",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'snapshotting', 'analyzing', 'synthesizing', "
            "'completed', 'failed', 'cancelled')",
            name="ck_analysis_runs_status",
        ),
        sa.CheckConstraint(
            "progress_pct >= 0 AND progress_pct <= 100",
            name="ck_analysis_runs_progress_pct",
        ),
        sa.CheckConstraint(
            "mention_count >= 0 AND processed_mention_count >= 0 "
            "AND processed_mention_count <= mention_count",
            name="ck_analysis_runs_mention_counts",
        ),
    )
    op.create_index(
        "ix_analysis_runs_project_created_at",
        "analysis_runs",
        ["project_id", "created_at"],
    )
    op.create_index(
        "ix_analysis_runs_collection_run",
        "analysis_runs",
        ["collection_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_runs_collection_run", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_project_created_at", table_name="analysis_runs")
    op.drop_table("analysis_runs")
