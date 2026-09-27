import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    schema_version: Literal[1] = 1
    analysis_run_id: uuid.UUID
    collection_run_id: uuid.UUID
    project_id: uuid.UUID
    enqueued_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AnalysisProgressEvent(StrictModel):
    schema_version: Literal[1] = 1
    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    analysis_run_id: uuid.UUID
    collection_run_id: uuid.UUID
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
