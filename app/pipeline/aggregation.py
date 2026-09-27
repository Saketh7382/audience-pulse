from collections import Counter, defaultdict
from collections.abc import Iterable

from app.contracts.analysis import (
    AggregationResult,
    AspectAggregate,
    DistributionItem,
    MentionAnalysis,
    MentionSnapshot,
    Sentiment,
)


def aggregate_mentions(
    snapshots: list[MentionSnapshot],
    analyses: list[MentionAnalysis],
) -> AggregationResult:
    """Calculate auditable distributions without asking an LLM to do arithmetic."""
    snapshots_by_id = {item.mention_id: item for item in snapshots}
    sentiment = Counter(item.sentiment.value for item in analyses)
    emotion = Counter(item.primary_emotion for item in analyses)
    intent = Counter(item.audience_intent.value for item in analyses)
    positive = Counter(point for item in analyses for point in item.positive_points)
    negative = Counter(point for item in analyses for point in item.negative_points)
    questions = Counter(
        item.question_topic
        for item in analyses
        if item.is_question and item.question_topic
    )
    comparisons = Counter(
        observation.compared_with
        for item in analyses
        for observation in item.comparisons
    )
    expectations = Counter(value for item in analyses for value in item.expectations)

    platform_sentiment: dict[str, Counter[str]] = defaultdict(Counter)
    asset_sentiment: dict[str, Counter[str]] = defaultdict(Counter)
    aspects: dict[str, Counter[str]] = defaultdict(Counter)
    for item in analyses:
        snapshot = snapshots_by_id[item.mention_id]
        platform_sentiment[snapshot.platform][item.sentiment.value] += 1
        asset_sentiment[str(snapshot.asset_id)][item.sentiment.value] += 1
        for observation in item.aspects:
            aspects[observation.aspect.value][
                _sentiment_bucket(observation.sentiment)
            ] += 1

    return AggregationResult(
        total_mentions=len(analyses),
        sentiment_distribution=_distribution(sentiment, len(analyses)),
        sentiment_by_platform={
            key: _distribution(values, sum(values.values()))
            for key, values in sorted(platform_sentiment.items())
        },
        sentiment_by_asset={
            key: _distribution(values, sum(values.values()))
            for key, values in sorted(asset_sentiment.items())
        },
        emotion_distribution=_distribution(emotion, len(analyses)),
        intent_distribution=_distribution(intent, len(analyses)),
        aspect_performance=[
            AspectAggregate(
                aspect=key,
                mentions=sum(values.values()),
                positive=values["positive"],
                mixed=values["mixed"],
                neutral=values["neutral"],
                negative=values["negative"],
            )
            for key, values in sorted(
                aspects.items(), key=lambda item: (-sum(item[1].values()), item[0])
            )
        ],
        positive_drivers=_top_distribution(positive),
        negative_drivers=_top_distribution(negative),
        question_topics=_top_distribution(questions),
        comparisons=_top_distribution(comparisons),
        expectations=_top_distribution(expectations),
    )


def _distribution(counter: Counter[str], total: int) -> list[DistributionItem]:
    return [
        DistributionItem(
            key=key,
            count=count,
            percentage=round((count / total * 100) if total else 0, 2),
        )
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _top_distribution(
    counter: Counter[str],
    *,
    limit: int = 30,
) -> list[DistributionItem]:
    total = sum(counter.values())
    return _distribution(Counter(dict(counter.most_common(limit))), total)


def _sentiment_bucket(value: Sentiment) -> str:
    if value in {Sentiment.STRONG_POSITIVE, Sentiment.POSITIVE}:
        return "positive"
    if value in {Sentiment.STRONG_NEGATIVE, Sentiment.NEGATIVE}:
        return "negative"
    return value.value


def distribution_map(values: Iterable[DistributionItem]) -> dict[str, float]:
    return {item.key: item.percentage for item in values}
