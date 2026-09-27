import json
import uuid
from datetime import datetime, timezone

import pytest

from app.contracts.analysis import (
    AssetTalentResult,
    EvidenceBackedFinding,
    ExecutivePulseResult,
    MentionAnalysis,
    MentionAnalysisBatch,
    MentionSnapshot,
    ModelUsageEntry,
    NarrativeSignalResult,
    Sentiment,
    SentimentStrength,
    StrategicRecommendation,
    SynthesisResult,
    ThemeResult,
)
from app.contracts.jobs import AnalysisJob
from app.core.config import Settings
from app.llm.base import GenerationResult, StructuredLLMProvider
from app.pipeline.orchestrator import AnalysisPipeline
from app.storage.local import LocalAnalysisStore


class FakeRepository:
    def __init__(self, mention: MentionSnapshot) -> None:
        self.mention = mention
        self.progress = []
        self.completed = None
        self.failed = None

    async def project_snapshot(self, project_id):
        return {
            "id": str(project_id),
            "title": "Test Film",
            "entities": {"lead_cast": ["Actor A"]},
            "target_assets": [],
            "sources": [],
            "connectors": [{"connector_key": "youtube_public", "is_enabled": True}],
        }

    async def collection_summary(self, collection_run_id):
        return {"id": str(collection_run_id), "status": "completed"}

    async def mentions(self, collection_run_id):
        return [self.mention]

    async def mark_progress(self, analysis_run_id, **values):
        self.progress.append(values)

    async def mark_completed(self, analysis_run_id, **values):
        self.completed = values

    async def mark_failed(self, analysis_run_id, error):
        self.failed = error

    async def previous_completed_analysis(self, **values):
        return None


class FakeLLM(StructuredLLMProvider):
    def __init__(self, mention_id: uuid.UUID) -> None:
        self.mention_id = mention_id
        self.calls = []

    async def generate_structured(self, *, stage, response_model, **values):
        self.calls.append(stage)
        if response_model is MentionAnalysisBatch:
            value = MentionAnalysisBatch(
                analyses=[
                    MentionAnalysis(
                        mention_id=self.mention_id,
                        language="Telugu-English code-mixed",
                        normalized_meaning_en="The BGM is excellent.",
                        sentiment=Sentiment.POSITIVE,
                        sentiment_strength=SentimentStrength.STRONG,
                        primary_emotion="excitement",
                        positive_points=["Background score"],
                        audience_intent="watch_theatre",
                        is_question=False,
                        confidence=0.95,
                    )
                ]
            )
        elif response_model is ThemeResult:
            value = ThemeResult(themes=[self._finding("Background score excitement")])
        elif response_model is AssetTalentResult:
            value = AssetTalentResult(asset_responses=[], talent_responses=[])
        elif response_model is NarrativeSignalResult:
            value = NarrativeSignalResult(
                audience_narrative=self._finding("Music is carrying early reaction"),
                strengths=[self._finding("Background score")],
                concerns=[],
                opportunities=[],
                risks=[],
                emerging_signals=[],
                information_gaps=[],
            )
        elif response_model is SynthesisResult:
            value = SynthesisResult(
                recommendations=[
                    StrategicRecommendation(
                        observation="The BGM drives positive conversation.",
                        interpretation="Music has strong recall.",
                        opportunity_or_risk="Music-led assets can sustain attention.",
                        recommended_action="Release a short score-led promo.",
                        supporting_mention_ids=[self.mention_id],
                    )
                ],
                executive_pulse=ExecutivePulseResult(
                    campaign_health="Positive early response",
                    what_is_working=["Background score"],
                    what_is_not_working=[],
                    what_changed=[],
                    watch_items=[],
                    next_actions=["Amplify music-led content"],
                    summary="Early response is positive and music-led.",
                ),
            )
        else:
            raise AssertionError(f"Unexpected schema {response_model}")
        return GenerationResult(
            value=value,
            usage=ModelUsageEntry(
                stage=stage,
                model=values["model"],
                prompt_tokens=10,
                completion_tokens=10,
                total_tokens=20,
            ),
        )

    def _finding(self, name):
        return EvidenceBackedFinding(
            name=name,
            observation="Audience explicitly praises the background score.",
            interpretation="Music is a positive campaign driver.",
            importance="high",
            sentiment=Sentiment.POSITIVE,
            supporting_mention_ids=[self.mention_id],
            supporting_platforms=["youtube_public"],
        )

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_pipeline_writes_final_files_and_resumes_without_more_llm_calls(tmp_path):
    mention = MentionSnapshot(
        mention_id=uuid.uuid4(),
        asset_id=uuid.uuid4(),
        platform="youtube_public",
        record_type="comment",
        text="BGM peaks ra!",
        published_at=datetime.now(timezone.utc),
        metrics={"like_count": 10},
        collection_tier="target_assets",
        asset_type="teaser",
        asset_title="Official teaser",
        asset_url="https://youtube.com/watch?v=test",
    )
    repository = FakeRepository(mention)
    llm = FakeLLM(mention.mention_id)
    settings = Settings(
        openrouter_api_key="test",
        analyzer_storage_root=tmp_path,
        analyzer_mention_batch_size=1,
    )
    pipeline = AnalysisPipeline(
        settings=settings,
        repository=repository,
        store=LocalAnalysisStore(tmp_path),
        llm=llm,
    )
    job = AnalysisJob(
        analysis_run_id=uuid.uuid4(),
        collection_run_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
    )

    result_path = await pipeline.run(job)
    call_count = len(llm.calls)
    second_path = await pipeline.run(job)

    assert second_path == result_path
    assert len(llm.calls) == call_count == 5
    assert repository.failed is None
    assert repository.completed is not None
    result = json.loads(result_path.read_text())
    assert result["aggregation"]["total_mentions"] == 1
    assert result["executive_pulse"]["campaign_health"] == "Positive early response"
    run_root = result_path.parent.parent
    assert (run_root / "input" / "mentions.jsonl").exists()
    assert (run_root / "final" / "executive_pulse.md").exists()
    assert (run_root / "final" / "evidence.jsonl").exists()
    assert (run_root / "final" / "model_usage.json").exists()
