import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnalysisStatus(str, Enum):
    QUEUED = "queued"
    SNAPSHOTTING = "snapshotting"
    ANALYZING = "analyzing"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AnalysisStage(str, Enum):
    INITIALIZING = "INITIALIZING"
    SNAPSHOTTING_INPUT = "SNAPSHOTTING_INPUT"
    MENTION_ANALYSIS = "MENTION_ANALYSIS"
    AGGREGATION = "AGGREGATION"
    THEME_ANALYSIS = "THEME_ANALYSIS"
    ASSET_TALENT_ANALYSIS = "ASSET_TALENT_ANALYSIS"
    NARRATIVE_SIGNAL_ANALYSIS = "NARRATIVE_SIGNAL_ANALYSIS"
    TREND_ANALYSIS = "TREND_ANALYSIS"
    SYNTHESIS = "SYNTHESIS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AnalysisJob(StrictModel):
    schema_version: Literal[1, 2, 3] = 3
    analysis_run_id: uuid.UUID
    collection_run_id: uuid.UUID | None = None
    collection_run_ids: list[uuid.UUID] = Field(default_factory=list)
    baseline_analysis_run_id: uuid.UUID | None = None
    incremental_collection_run_ids: list[uuid.UUID] = Field(default_factory=list)
    project_id: uuid.UUID
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def normalize_collection_runs(self) -> "AnalysisJob":
        run_ids = list(self.collection_run_ids)
        if not run_ids and self.collection_run_id is not None:
            run_ids = [self.collection_run_id]
        if not run_ids:
            raise ValueError("At least one collection run is required")
        if len(set(run_ids)) != len(run_ids):
            raise ValueError("collection_run_ids must not contain duplicates")
        if self.collection_run_id is not None and self.collection_run_id not in run_ids:
            raise ValueError("collection_run_id must be included in collection_run_ids")
        incremental_ids = list(self.incremental_collection_run_ids) or run_ids
        if len(set(incremental_ids)) != len(incremental_ids):
            raise ValueError(
                "incremental_collection_run_ids must not contain duplicates"
            )
        if not set(incremental_ids).issubset(run_ids):
            raise ValueError(
                "incremental_collection_run_ids must be included in collection_run_ids"
            )
        self.collection_run_ids = run_ids
        self.collection_run_id = self.collection_run_id or run_ids[0]
        self.incremental_collection_run_ids = incremental_ids
        return self


class AnalysisProgressEvent(StrictModel):
    schema_version: Literal[1, 2, 3] = 3
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    analysis_run_id: uuid.UUID
    collection_run_id: uuid.UUID
    collection_run_ids: list[uuid.UUID] = Field(default_factory=list)
    project_id: uuid.UUID
    status: AnalysisStatus
    current_stage: AnalysisStage
    progress_pct: int = Field(ge=0, le=100)
    processed_mentions: int = Field(default=0, ge=0)
    total_mentions: int = Field(default=0, ge=0)
    manifest_path: str | None = None
    final_result_path: str | None = None
    executive_report_path: str | None = None
    error_message: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
