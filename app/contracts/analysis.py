import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class Sentiment(str, Enum):
    STRONG_POSITIVE = "strong_positive"
    POSITIVE = "positive"
    MIXED = "mixed"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    STRONG_NEGATIVE = "strong_negative"


class SentimentStrength(str, Enum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class AudienceIntent(str, Enum):
    WATCH_THEATRE = "watch_theatre"
    BOOK_FIRST_DAY = "book_first_day"
    WAIT_FOR_REVIEWS = "wait_for_reviews"
    WAIT_FOR_OTT = "wait_for_ott"
    RECOMMEND_OR_SHARE = "recommend_or_share"
    REWATCH_PROMO = "rewatch_promo"
    LISTEN_TO_SOUNDTRACK = "listen_to_soundtrack"
    AVOID = "avoid"
    UNDECIDED = "undecided"
    NONE = "none"


class FilmAspect(str, Enum):
    LEAD_ACTOR = "lead_actor"
    SUPPORTING_CAST = "supporting_cast"
    CHARACTER = "character"
    DIRECTOR = "director"
    STORY = "story"
    SCREENPLAY = "screenplay"
    DIALOGUE = "dialogue"
    MUSIC = "music"
    BGM = "bgm"
    SONG = "song"
    CINEMATOGRAPHY = "cinematography"
    VISUALS = "visuals"
    VFX = "vfx"
    ACTION = "action"
    COMEDY = "comedy"
    ROMANCE = "romance"
    COSTUME_OR_LOOK = "costume_or_look"
    PRODUCTION_SCALE = "production_scale"
    EDITING = "editing"
    POSTER = "poster"
    TEASER = "teaser"
    TRAILER = "trailer"
    PROMOTION = "promotion"
    RELEASE_STRATEGY = "release_strategy"
    OVERALL_FILM = "overall_film"
    OTHER = "other"


class MentionSnapshot(StrictModel):
    mention_id: uuid.UUID
    asset_id: uuid.UUID
    platform: str
    record_type: str
    text: str
    published_at: datetime
    metrics: dict[str, Any] = Field(default_factory=dict)
    collection_tier: str
    asset_type: str
    asset_title: str | None = None
    asset_url: str
    source_name: str | None = None


class AspectObservation(StrictModel):
    aspect: FilmAspect
    sentiment: Sentiment
    detail: str


class ComparisonObservation(StrictModel):
    subject: str
    compared_with: str
    implication: Literal["praise", "criticism", "neutral", "unclear"]


class MentionAnalysis(StrictModel):
    mention_id: uuid.UUID
    language: str
    normalized_meaning_en: str | None = None
    sentiment: Sentiment
    sentiment_strength: SentimentStrength
    primary_emotion: str
    secondary_emotions: list[str] = Field(default_factory=list)
    aspects: list[AspectObservation] = Field(default_factory=list)
    positive_points: list[str] = Field(default_factory=list)
    negative_points: list[str] = Field(default_factory=list)
    audience_intent: AudienceIntent
    is_question: bool
    question_topic: str | None = None
    comparisons: list[ComparisonObservation] = Field(default_factory=list)
    expectations: list[str] = Field(default_factory=list)
    speculation: list[str] = Field(default_factory=list)
    entities_discussed: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class MentionAnalysisBatch(StrictModel):
    analyses: list[MentionAnalysis]


class DistributionItem(StrictModel):
    key: str
    count: int = Field(ge=0)
    percentage: float = Field(ge=0, le=100)


class AspectAggregate(StrictModel):
    aspect: str
    mentions: int = Field(ge=0)
    positive: int = Field(ge=0)
    mixed: int = Field(ge=0)
    neutral: int = Field(ge=0)
    negative: int = Field(ge=0)


class AggregationResult(StrictModel):
    total_mentions: int = Field(ge=0)
    sentiment_distribution: list[DistributionItem]
    sentiment_by_platform: dict[str, list[DistributionItem]]
    sentiment_by_asset: dict[str, list[DistributionItem]]
    emotion_distribution: list[DistributionItem]
    intent_distribution: list[DistributionItem]
    aspect_performance: list[AspectAggregate]
    positive_drivers: list[DistributionItem]
    negative_drivers: list[DistributionItem]
    question_topics: list[DistributionItem]
    comparisons: list[DistributionItem]
    expectations: list[DistributionItem]


class EvidenceBackedFinding(StrictModel):
    name: str
    observation: str
    interpretation: str
    importance: Literal["low", "medium", "high", "critical"]
    sentiment: Sentiment | None = None
    supporting_mention_ids: list[uuid.UUID] = Field(min_length=1)
    supporting_asset_ids: list[uuid.UUID] = Field(default_factory=list)
    supporting_platforms: list[str] = Field(default_factory=list)


class ThemeResult(StrictModel):
    themes: list[EvidenceBackedFinding]


class EntityResponse(StrictModel):
    entity: str
    entity_type: Literal["asset", "talent", "character", "other"]
    observation: str
    interpretation: str
    sentiment: Sentiment
    supporting_mention_ids: list[uuid.UUID] = Field(min_length=1)


class AssetTalentResult(StrictModel):
    asset_responses: list[EntityResponse]
    talent_responses: list[EntityResponse]


class NarrativeSignalResult(StrictModel):
    audience_narrative: EvidenceBackedFinding | None = None
    strengths: list[EvidenceBackedFinding]
    concerns: list[EvidenceBackedFinding]
    opportunities: list[EvidenceBackedFinding]
    risks: list[EvidenceBackedFinding]
    emerging_signals: list[EvidenceBackedFinding]
    information_gaps: list[EvidenceBackedFinding]


class TrendChange(StrictModel):
    metric: str
    direction: Literal["increased", "decreased", "appeared", "disappeared", "stable"]
    previous_value: float | None = None
    current_value: float | None = None
    interpretation: str
    supporting_mention_ids: list[uuid.UUID] = Field(default_factory=list)


class TrendResult(StrictModel):
    comparison_analysis_run_id: uuid.UUID | None = None
    skipped_reason: str | None = None
    changes: list[TrendChange] = Field(default_factory=list)


class StrategicRecommendation(StrictModel):
    observation: str
    interpretation: str
    opportunity_or_risk: str
    recommended_action: str
    supporting_mention_ids: list[uuid.UUID] = Field(min_length=1)


class ExecutivePulseResult(StrictModel):
    campaign_health: str
    what_is_working: list[str]
    what_is_not_working: list[str]
    what_changed: list[str]
    watch_items: list[str]
    next_actions: list[str]
    summary: str


class SynthesisResult(StrictModel):
    recommendations: list[StrategicRecommendation]
    executive_pulse: ExecutivePulseResult


class ModelUsageEntry(StrictModel):
    stage: str
    model: str
    generation_id: str | None = None
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StageManifest(StrictModel):
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    output_paths: list[str] = Field(default_factory=list)
    completed_items: int = Field(default=0, ge=0)
    completed_at: datetime | None = None


class AnalysisManifest(StrictModel):
    schema_version: Literal[1, 2, 3] = 3
    analysis_run_id: uuid.UUID
    collection_run_id: uuid.UUID
    collection_run_ids: list[uuid.UUID] = Field(default_factory=list)
    baseline_analysis_run_id: uuid.UUID | None = None
    incremental_collection_run_ids: list[uuid.UUID] = Field(default_factory=list)
    project_id: uuid.UUID
    analyzer_version: str
    prompt_bundle_version: str
    status: str = "queued"
    current_stage: str = "INITIALIZING"
    input_mentions: int = Field(default=0, ge=0)
    completed_mentions: int = Field(default=0, ge=0)
    mention_cache_hits: int = Field(default=0, ge=0)
    mention_cache_misses: int = Field(default=0, ge=0)
    stages: dict[str, StageManifest] = Field(default_factory=dict)
    model_usage: list[ModelUsageEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_completed_count(self) -> "AnalysisManifest":
        if self.completed_mentions > self.input_mentions:
            raise ValueError("completed_mentions cannot exceed input_mentions")
        if not self.collection_run_ids:
            self.collection_run_ids = [self.collection_run_id]
        if self.collection_run_id not in self.collection_run_ids:
            raise ValueError("collection_run_id must be included in collection_run_ids")
        if not self.incremental_collection_run_ids:
            self.incremental_collection_run_ids = list(self.collection_run_ids)
        if not set(self.incremental_collection_run_ids).issubset(
            self.collection_run_ids
        ):
            raise ValueError(
                "incremental_collection_run_ids must be included in collection_run_ids"
            )
        return self
