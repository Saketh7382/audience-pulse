import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnalysisRun(Base):
    """Database metadata for one immutable analysis attempt.

    Analytical content deliberately does not belong in this table. The row is the
    durable lifecycle/index record that points clients to a manifest and final
    files below the configured storage root.
    """

    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'snapshotting', 'analyzing', 'synthesizing', "
            "'completed', 'failed', 'cancelled')",
            name="ck_analysis_runs_status",
        ),
        CheckConstraint(
            "progress_pct >= 0 AND progress_pct <= 100",
            name="ck_analysis_runs_progress_pct",
        ),
        CheckConstraint(
            "mention_count >= 0 AND processed_mention_count >= 0 "
            "AND processed_mention_count <= mention_count",
            name="ck_analysis_runs_mention_counts",
        ),
        Index(
            "ix_analysis_runs_project_created_at",
            "project_id",
            "created_at",
        ),
        Index(
            "ix_analysis_runs_collection_run",
            "collection_run_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    collection_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    current_stage: Mapped[str] = mapped_column(
        String(100), nullable=False, default="INITIALIZING"
    )
    progress_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_backend: Mapped[str] = mapped_column(
        String(32), nullable=False, default="local"
    )
    manifest_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    final_result_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    executive_report_path: Mapped[str | None] = mapped_column(
        String(1000), nullable=True
    )
    analyzer_version: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_bundle_version: Mapped[str] = mapped_column(String(100), nullable=False)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_mention_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    model_usage: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
