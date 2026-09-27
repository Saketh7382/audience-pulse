import uuid
from datetime import datetime, timezone

from app.contracts.analysis import (
    AspectObservation,
    FilmAspect,
    MentionAnalysis,
    MentionSnapshot,
    Sentiment,
    SentimentStrength,
)
from app.pipeline.aggregation import aggregate_mentions


def test_aggregation_calculates_percentages_and_aspect_buckets():
    asset_id = uuid.uuid4()
    snapshots = [
        MentionSnapshot(
            mention_id=uuid.uuid4(),
            asset_id=asset_id,
            platform="youtube_public",
            record_type="comment",
            text="Great BGM",
            published_at=datetime.now(timezone.utc),
            collection_tier="target_assets",
            asset_type="teaser",
            asset_url="https://youtube.com/watch?v=test",
        ),
        MentionSnapshot(
            mention_id=uuid.uuid4(),
            asset_id=asset_id,
            platform="youtube_public",
            record_type="comment",
            text="VFX looks unfinished",
            published_at=datetime.now(timezone.utc),
            collection_tier="target_assets",
            asset_type="teaser",
            asset_url="https://youtube.com/watch?v=test",
        ),
    ]
    analyses = [
        MentionAnalysis(
            mention_id=snapshots[0].mention_id,
            language="English",
            sentiment=Sentiment.POSITIVE,
            sentiment_strength=SentimentStrength.STRONG,
            primary_emotion="excitement",
            aspects=[
                AspectObservation(
                    aspect=FilmAspect.BGM,
                    sentiment=Sentiment.POSITIVE,
                    detail="BGM praised",
                )
            ],
            positive_points=["Background score"],
            audience_intent="none",
            is_question=False,
            confidence=0.9,
        ),
        MentionAnalysis(
            mention_id=snapshots[1].mention_id,
            language="English",
            sentiment=Sentiment.NEGATIVE,
            sentiment_strength=SentimentStrength.MODERATE,
            primary_emotion="disappointment",
            aspects=[
                AspectObservation(
                    aspect=FilmAspect.VFX,
                    sentiment=Sentiment.NEGATIVE,
                    detail="VFX criticized",
                )
            ],
            negative_points=["Unfinished VFX"],
            audience_intent="none",
            is_question=False,
            confidence=0.9,
        ),
    ]

    result = aggregate_mentions(snapshots, analyses)

    assert result.total_mentions == 2
    assert {item.key: item.percentage for item in result.sentiment_distribution} == {
        "negative": 50.0,
        "positive": 50.0,
    }
    assert {item.aspect: item.mentions for item in result.aspect_performance} == {
        "bgm": 1,
        "vfx": 1,
    }
