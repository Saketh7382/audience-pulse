import uuid
from datetime import datetime, timezone

from app.contracts.analysis import (
    AudienceIntent,
    MentionAnalysis,
    MentionSnapshot,
    Sentiment,
    SentimentStrength,
)
from app.storage.local import LocalAnalysisStore
from app.storage.mention_cache import MentionAnalysisCache


def snapshot(
    *, text: str = "Great teaser", metrics: dict | None = None
) -> MentionSnapshot:
    return MentionSnapshot(
        mention_id=uuid.UUID("5147e3cc-e895-4f46-ba26-d07c16c5bf47"),
        asset_id=uuid.uuid4(),
        platform="youtube_public",
        record_type="comment",
        text=text,
        published_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        collection_tier="target_assets",
        asset_type="teaser",
        asset_url="https://youtube.com/watch?v=test",
        metrics=metrics or {},
    )


def analysis(mention_id: uuid.UUID) -> MentionAnalysis:
    return MentionAnalysis(
        mention_id=mention_id,
        language="English",
        sentiment=Sentiment.POSITIVE,
        sentiment_strength=SentimentStrength.MODERATE,
        primary_emotion="excitement",
        audience_intent=AudienceIntent.WATCH_THEATRE,
        is_question=False,
        confidence=0.9,
    )


def cache(tmp_path, *, prompt_version: str = "v1") -> MentionAnalysisCache:
    return MentionAnalysisCache(
        LocalAnalysisStore(tmp_path),
        analyzer_version="0.1.0",
        prompt_bundle_version=prompt_version,
        requested_model="google/gemini-3.5-flash-lite",
    )


def test_cache_reuses_only_the_exact_versioned_immutable_input(tmp_path):
    original = snapshot()
    value = analysis(original.mention_id)
    cache(tmp_path).put(original, value)

    assert cache(tmp_path).get(original) == value
    assert cache(tmp_path).get(snapshot(text="Corrected teaser text")) is None
    assert cache(tmp_path, prompt_version="v2").get(original) is None


def test_cache_ignores_mutable_engagement_metrics(tmp_path):
    original = snapshot(metrics={"like_count": 10, "reply_count": 2})
    value = analysis(original.mention_id)
    cache(tmp_path).put(original, value)

    refreshed = snapshot(metrics={"like_count": 500, "reply_count": 90})
    assert cache(tmp_path).get(refreshed) == value
