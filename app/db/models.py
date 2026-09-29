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
    UniqueConstraint,
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
        UniqueConstraint(
            "project_id",
            "input_signature",
            name="uq_analysis_runs_input_signature",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    # PostgreSQL owns and enforces the cross-service foreign keys. The analyzer
    # intentionally maps these as scalar IDs so ORM flushes do not require the
    # complete Control Plane model registry.
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    collection_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    input_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
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

    @property
    def collection_run_ids(self) -> list[uuid.UUID]:
        """Run IDs explicitly loaded by the repository from the association table."""
        return getattr(self, "_collection_run_ids", [self.collection_run_id])

    @property
    def incremental_collection_run_ids(self) -> list[uuid.UUID]:
        return getattr(self, "_incremental_collection_run_ids", self.collection_run_ids)


class AnalysisRunCollectionRun(Base):
    """Ordered collection runs included in one immutable analysis input."""

    __tablename__ = "analysis_run_collection_runs"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id", "position", name="uq_analysis_run_collection_position"
        ),
    )

    analysis_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_runs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    collection_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_incremental: Mapped[bool] = mapped_column(nullable=False, default=True)
