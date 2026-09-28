import hashlib
import logging
import math
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from app.contracts.analysis import (
    AggregationResult,
    AnalysisManifest,
    AssetTalentResult,
    ExecutivePulseResult,
    MentionAnalysis,
    MentionAnalysisBatch,
    MentionSnapshot,
    NarrativeSignalResult,
    StageManifest,
    SynthesisResult,
    ThemeResult,
    TrendResult,
)
from app.contracts.jobs import (
    AnalysisJob,
    AnalysisProgressEvent,
    AnalysisStage,
    AnalysisStatus,
)
from app.core.config import Settings
from app.db.repository import AnalysisRepository
from app.llm.base import StructuredLLMProvider
from app.llm.prompts import (
    MENTION_SYSTEM_PROMPT,
    evidence_system_prompt,
    mention_prompt,
    mention_retry_prompt,
    structured_context_prompt,
)
from app.pipeline.aggregation import aggregate_mentions, distribution_map
from app.pipeline.evidence import (
    build_evidence_records,
    select_evidence,
    validate_evidence_ids,
)
from app.pipeline.report import executive_markdown
from app.storage.local import LocalAnalysisStore, RunPaths
from app.storage.mention_cache import MentionAnalysisCache

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
ProgressReporter = Callable[[AnalysisProgressEvent], Awaitable[None]]


class AnalysisPipeline:
    """Resumable, evidence-validated audience intelligence pipeline."""

    def __init__(
        self,
        *,
        settings: Settings,
        repository: AnalysisRepository,
        store: LocalAnalysisStore,
        llm: StructuredLLMProvider,
        report_progress: ProgressReporter | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.store = store
        self.llm = llm
        self.mention_cache = MentionAnalysisCache(
            store,
            analyzer_version=settings.analyzer_version,
            prompt_bundle_version=settings.prompt_bundle_version,
            requested_model=settings.analyzer_mention_model,
        )
        self.report_progress = report_progress

    async def run(self, job: AnalysisJob) -> Path:
        metadata = await self.repository.get(job.analysis_run_id)
        if metadata is None:
            raise RuntimeError(f"Analysis run {job.analysis_run_id} was not found")
        if metadata.project_id != job.project_id or set(
            metadata.collection_run_ids
        ) != set(job.collection_run_ids):
            raise RuntimeError("Analysis job identity does not match database metadata")

        paths = self.store.paths(
            project_id=job.project_id,
            collection_run_id=job.collection_run_id,
            analysis_run_id=job.analysis_run_id,
        )
        self.store.initialize(paths)
        with self.store.acquire_run_lock(paths):
            manifest = self._load_or_create_manifest(job, paths)
            if manifest.status == AnalysisStatus.COMPLETED.value:
                final_path = paths.final / "audience_pulse.json"
                if not final_path.exists():
                    raise RuntimeError(
                        "Completed manifest is missing audience_pulse.json"
                    )
                return final_path
            try:
                return await self._execute(job, paths, manifest)
            except Exception as exc:
                manifest.status = AnalysisStatus.FAILED.value
                manifest.current_stage = AnalysisStage.FAILED.value
                manifest.error_message = str(exc)[:4000]
                manifest.updated_at = datetime.now(timezone.utc)
                self.store.save_manifest(paths, manifest)
                await self.repository.mark_failed(job.analysis_run_id, str(exc))
                await self._publish(
                    job,
                    manifest,
                    AnalysisStatus.FAILED,
                    AnalysisStage.FAILED,
                    0,
                    error_message=str(exc)[:2000],
                )
                logger.exception("Audience Pulse analysis failed for this run.")
                raise

    async def _execute(
        self,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
    ) -> Path:
        project, collection, snapshots = await self._snapshot(job, paths, manifest)
        title = project["title"]
        logger.info('Starting audience analysis for project "%s".', title)

        analyses = await self._mention_analysis(job, paths, manifest, snapshots)
        aggregation = await self._aggregation(job, paths, manifest, snapshots, analyses)
        evidence = select_evidence(snapshots, analyses)
        valid_ids = {item.mention_id for item in snapshots}

        if snapshots:
            themes = await self._themes(
                job, paths, manifest, aggregation, evidence, valid_ids
            )
            asset_talent = await self._asset_talent(
                job,
                paths,
                manifest,
                project,
                aggregation,
                evidence,
                valid_ids,
            )
            narrative = await self._narrative(
                job,
                paths,
                manifest,
                aggregation,
                themes,
                asset_talent,
                evidence,
                valid_ids,
            )
        else:
            themes = ThemeResult(themes=[])
            asset_talent = AssetTalentResult(asset_responses=[], talent_responses=[])
            narrative = NarrativeSignalResult(
                audience_narrative=None,
                strengths=[],
                concerns=[],
                opportunities=[],
                risks=[],
                emerging_signals=[],
                information_gaps=[],
            )
            await self._persist_empty_insight_stages(
                job, paths, manifest, themes, asset_talent, narrative
            )

        trends = await self._trends(
            job,
            paths,
            manifest,
            aggregation,
            evidence,
            valid_ids,
        )
        synthesis = await self._synthesis(
            job,
            paths,
            manifest,
            aggregation,
            themes,
            asset_talent,
            narrative,
            trends,
            evidence,
            valid_ids,
        )
        final_path = await self._finalize(
            job=job,
            paths=paths,
            manifest=manifest,
            project=project,
            collection=collection,
            aggregation=aggregation,
            themes=themes,
            asset_talent=asset_talent,
            narrative=narrative,
            trends=trends,
            synthesis=synthesis,
            snapshots=snapshots,
        )
        logger.info('Audience Pulse completed for project "%s".', title)
        return final_path

    def _load_or_create_manifest(
        self, job: AnalysisJob, paths: RunPaths
    ) -> AnalysisManifest:
        manifest = self.store.load_manifest(paths)
        if manifest is None:
            manifest = AnalysisManifest(
                analysis_run_id=job.analysis_run_id,
                collection_run_id=job.collection_run_id,
                collection_run_ids=job.collection_run_ids,
                project_id=job.project_id,
                analyzer_version=self.settings.analyzer_version,
                prompt_bundle_version=self.settings.prompt_bundle_version,
            )
            self.store.save_manifest(paths, manifest)
        if (
            manifest.analysis_run_id != job.analysis_run_id
            or set(manifest.collection_run_ids) != set(job.collection_run_ids)
            or manifest.project_id != job.project_id
        ):
            raise RuntimeError("Manifest identity does not match the analysis job")
        return manifest

    async def _snapshot(
        self,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
    ) -> tuple[dict[str, Any], dict[str, Any], list[MentionSnapshot]]:
        stage = "snapshot"
        project_path = paths.input / "project_snapshot.json"
        collection_path = paths.input / "collection_summary.json"
        mentions_path = paths.input / "mentions.jsonl"
        if self._stage_completed(manifest, stage):
            _verify_input_checksums(paths.input)
            return (
                self.store.read_json(project_path),
                self.store.read_json(collection_path),
                [
                    MentionSnapshot.model_validate(item)
                    for item in self.store.iter_jsonl(mentions_path)
                ],
            )

        logger.info("Freezing the project and collected audience data for analysis.")
        await self._start_stage(
            job,
            paths,
            manifest,
            stage,
            AnalysisStatus.SNAPSHOTTING,
            AnalysisStage.SNAPSHOTTING_INPUT,
            2,
        )
        project = await self.repository.project_snapshot(job.project_id)
        run_summaries = [
            await self.repository.collection_summary(run_id)
            for run_id in job.collection_run_ids
        ]
        collection = {
            "collection_run_ids": [str(run_id) for run_id in job.collection_run_ids],
            "runs": run_summaries,
        }
        snapshots_by_id: dict[uuid.UUID, MentionSnapshot] = {}
        for run_id in job.collection_run_ids:
            for snapshot in await self.repository.mentions(run_id):
                snapshots_by_id.setdefault(snapshot.mention_id, snapshot)
        snapshots = sorted(
            snapshots_by_id.values(),
            key=lambda item: (item.published_at, str(item.mention_id)),
        )
        self.store.write_json(project_path, project)
        self.store.write_json(collection_path, collection)
        self.store.write_jsonl(mentions_path, snapshots)
        checksums = {
            path.name: _sha256(path)
            for path in (project_path, collection_path, mentions_path)
        }
        self.store.write_json(paths.input / "checksums.json", checksums)
        manifest.input_mentions = len(snapshots)
        await self._complete_stage(
            job,
            paths,
            manifest,
            stage,
            [
                project_path,
                collection_path,
                mentions_path,
                paths.input / "checksums.json",
            ],
            AnalysisStatus.ANALYZING,
            AnalysisStage.MENTION_ANALYSIS,
            5,
        )
        return project, collection, snapshots

    async def _mention_analysis(
        self,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
        snapshots: list[MentionSnapshot],
    ) -> list[MentionAnalysis]:
        stage = "mention_analysis"
        directory = paths.stages / "01_mention_analysis" / "batches"
        directory.mkdir(parents=True, exist_ok=True)
        batch_size = self.settings.analyzer_mention_batch_size
        total_batches = math.ceil(len(snapshots) / batch_size) if snapshots else 0
        logger.info(
            "Analyzing %s audience mentions in %s immutable batches.",
            len(snapshots),
            total_batches,
        )
        await self._start_stage(
            job,
            paths,
            manifest,
            stage,
            AnalysisStatus.ANALYZING,
            AnalysisStage.MENTION_ANALYSIS,
            5,
        )

        snapshots_by_id = {item.mention_id: item for item in snapshots}
        cached_by_id = {
            snapshot.mention_id: cached
            for snapshot in snapshots
            if (cached := self.mention_cache.get(snapshot)) is not None
        }
        manifest.mention_cache_hits = len(cached_by_id)
        manifest.mention_cache_misses = len(snapshots) - len(cached_by_id)
        manifest.updated_at = datetime.now(timezone.utc)
        self.store.save_manifest(paths, manifest)
        if cached_by_id:
            logger.info(
                "Reusing prior analysis for %s mentions; %s new mentions require "
                "model processing.",
                len(cached_by_id),
                manifest.mention_cache_misses,
            )

        all_analyses: list[MentionAnalysis] = []
        for index, start in enumerate(range(0, len(snapshots), batch_size), start=1):
            batch = snapshots[start : start + batch_size]
            output_path = directory / f"batch-{index:06d}.jsonl"
            expected_ids = {item.mention_id for item in batch}
            if output_path.exists():
                completed = [
                    MentionAnalysis.model_validate(item)
                    for item in self.store.iter_jsonl(output_path)
                ]
                _validate_batch_ids(completed, expected_ids)
                for analysis in completed:
                    self.mention_cache.put(
                        snapshots_by_id[analysis.mention_id], analysis
                    )
                logger.info(
                    "Mention batch %s of %s is already complete; reusing it.",
                    index,
                    total_batches,
                )
            else:
                logger.info("Analyzing mention batch %s of %s.", index, total_batches)
                partial_path = directory / f"batch-{index:06d}.partial.jsonl"
                completed_by_id: dict[uuid.UUID, MentionAnalysis] = {
                    item.mention_id: cached_by_id[item.mention_id]
                    for item in batch
                    if item.mention_id in cached_by_id
                }
                if partial_path.exists():
                    partial = [
                        MentionAnalysis.model_validate(item)
                        for item in self.store.iter_jsonl(partial_path)
                    ]
                    _validate_partial_batch_ids(partial, expected_ids)
                    completed_by_id.update((item.mention_id, item) for item in partial)
                    logger.info(
                        "Resuming mention batch %s with %s of %s mentions already "
                        "checkpointed.",
                        index,
                        len(completed_by_id),
                        len(batch),
                    )

                for attempt in range(
                    1, self.settings.analyzer_mention_batch_max_attempts + 1
                ):
                    remaining = [
                        item for item in batch if item.mention_id not in completed_by_id
                    ]
                    if not remaining:
                        break
                    generated = await self.llm.generate_structured(
                        stage=stage,
                        model=self.settings.analyzer_mention_model,
                        fallback_models=self.settings.analyzer_fallback_model_list,
                        system_prompt=MENTION_SYSTEM_PROMPT,
                        user_prompt=(
                            mention_prompt(remaining)
                            if attempt == 1 and not completed_by_id
                            else mention_retry_prompt(remaining)
                        ),
                        response_model=MentionAnalysisBatch,
                    )
                    manifest.model_usage.append(generated.usage)
                    for analysis in generated.value.analyses:
                        if analysis.mention_id in expected_ids:
                            completed_by_id.setdefault(analysis.mention_id, analysis)
                            self.mention_cache.put(
                                snapshots_by_id[analysis.mention_id], analysis
                            )
                    completed = [
                        completed_by_id[item.mention_id]
                        for item in batch
                        if item.mention_id in completed_by_id
                    ]
                    _validate_partial_batch_ids(completed, expected_ids)
                    self.store.write_jsonl(partial_path, completed)
                    manifest.updated_at = datetime.now(timezone.utc)
                    self.store.save_manifest(paths, manifest)
                    missing_count = len(expected_ids - set(completed_by_id))
                    if missing_count:
                        logger.warning(
                            "Mention batch %s returned %s of %s required analyses; "
                            "retrying the %s missing mentions.",
                            index,
                            len(completed_by_id),
                            len(batch),
                            missing_count,
                        )

                completed = [
                    completed_by_id[item.mention_id]
                    for item in batch
                    if item.mention_id in completed_by_id
                ]
                _validate_batch_ids(completed, expected_ids)
                self.store.write_jsonl(output_path, completed)
                partial_path.unlink(missing_ok=True)
            all_analyses.extend(completed)
            manifest.completed_mentions = len(all_analyses)
            manifest.updated_at = datetime.now(timezone.utc)
            self.store.save_manifest(paths, manifest)
            progress = 5 + round(40 * len(all_analyses) / max(len(snapshots), 1))
            await self.repository.mark_progress(
                job.analysis_run_id,
                status=AnalysisStatus.ANALYZING,
                stage=AnalysisStage.MENTION_ANALYSIS,
                progress_pct=progress,
                mention_count=len(snapshots),
                processed_mention_count=len(all_analyses),
                model_usage=manifest.model_usage,
            )
            await self._publish(
                job,
                manifest,
                AnalysisStatus.ANALYZING,
                AnalysisStage.MENTION_ANALYSIS,
                progress,
            )

        await self._complete_stage(
            job,
            paths,
            manifest,
            stage,
            sorted(directory.glob("batch-*.jsonl")),
            AnalysisStatus.ANALYZING,
            AnalysisStage.AGGREGATION,
            45,
        )
        return all_analyses

    async def _aggregation(
        self,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
        snapshots: list[MentionSnapshot],
        analyses: list[MentionAnalysis],
    ) -> AggregationResult:
        stage = "aggregation"
        output = paths.stages / "02_aggregation" / "result.json"
        if output.exists():
            result = AggregationResult.model_validate(self.store.read_json(output))
        else:
            logger.info(
                "Calculating sentiment, emotion, intent, and aspect statistics."
            )
            await self._start_stage(
                job,
                paths,
                manifest,
                stage,
                AnalysisStatus.ANALYZING,
                AnalysisStage.AGGREGATION,
                46,
            )
            result = aggregate_mentions(snapshots, analyses)
            self.store.write_json(output, result)
        await self._complete_stage(
            job,
            paths,
            manifest,
            stage,
            [output],
            AnalysisStatus.ANALYZING,
            AnalysisStage.THEME_ANALYSIS,
            50,
        )
        return result

    async def _themes(
        self,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
        aggregation: AggregationResult,
        evidence: list[dict[str, Any]],
        valid_ids: set[uuid.UUID],
    ) -> ThemeResult:
        logger.info("Identifying the dominant audience conversations and themes.")
        return await self._structured_stage(
            job=job,
            paths=paths,
            manifest=manifest,
            key="themes",
            directory="03_themes",
            stage=AnalysisStage.THEME_ANALYSIS,
            status=AnalysisStatus.ANALYZING,
            start_progress=51,
            end_progress=60,
            model=self.settings.analyzer_theme_model,
            responsibility="theme and conversation analysis",
            task=(
                "Identify dominant and meaningful conversation themes. Each theme "
                "must explain what audiences said, what it means, its importance, "
                "sentiment, and actual supporting IDs. Do not force themes."
            ),
            context={
                "aggregates": aggregation.model_dump(mode="json"),
                "selected_evidence": evidence,
            },
            response_model=ThemeResult,
            valid_ids=valid_ids,
        )

    async def _asset_talent(
        self,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
        project: dict[str, Any],
        aggregation: AggregationResult,
        evidence: list[dict[str, Any]],
        valid_ids: set[uuid.UUID],
    ) -> AssetTalentResult:
        logger.info("Evaluating campaign assets, talent, and characters.")
        return await self._structured_stage(
            job=job,
            paths=paths,
            manifest=manifest,
            key="asset_talent",
            directory="04_asset_talent",
            stage=AnalysisStage.ASSET_TALENT_ANALYSIS,
            status=AnalysisStatus.ANALYZING,
            start_progress=61,
            end_progress=70,
            model=self.settings.analyzer_theme_model,
            responsibility="campaign asset and talent response analysis",
            task=(
                "Explain what each materially discussed asset accomplished and "
                "which named talent or characters are winning or losing attention. "
                "Omit entities without material evidence."
            ),
            context={
                "project_entities": project.get("entities", {}),
                "configured_assets": project.get("target_assets", []),
                "aggregates": aggregation.model_dump(mode="json"),
                "selected_evidence": evidence,
            },
            response_model=AssetTalentResult,
            valid_ids=valid_ids,
        )

    async def _narrative(
        self,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
        aggregation: AggregationResult,
        themes: ThemeResult,
        asset_talent: AssetTalentResult,
        evidence: list[dict[str, Any]],
        valid_ids: set[uuid.UUID],
    ) -> NarrativeSignalResult:
        logger.info(
            "Interpreting the audience narrative, strengths, and warning signals."
        )
        return await self._structured_stage(
            job=job,
            paths=paths,
            manifest=manifest,
            key="narratives_signals",
            directory="05_narratives_signals",
            stage=AnalysisStage.NARRATIVE_SIGNAL_ANALYSIS,
            status=AnalysisStatus.ANALYZING,
            start_progress=71,
            end_progress=80,
            model=self.settings.analyzer_narrative_model,
            responsibility="audience narrative and decision-signal analysis",
            task=(
                "State the collective audience narrative, then identify material "
                "strengths, concerns, opportunities, risks, emerging signals, and "
                "information gaps. A concern is not automatically a risk. If no "
                "material item exists, return an empty list."
            ),
            context={
                "aggregates": aggregation.model_dump(mode="json"),
                "themes": themes.model_dump(mode="json"),
                "asset_and_talent": asset_talent.model_dump(mode="json"),
                "selected_evidence": evidence,
            },
            response_model=NarrativeSignalResult,
            valid_ids=valid_ids,
        )

    async def _trends(
        self,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
        aggregation: AggregationResult,
        evidence: list[dict[str, Any]],
        valid_ids: set[uuid.UUID],
    ) -> TrendResult:
        stage_key = "trends"
        output = paths.stages / "06_trends" / "result.json"
        if output.exists():
            result = TrendResult.model_validate(self.store.read_json(output))
            validate_evidence_ids(result, valid_ids)
            await self._complete_stage(
                job,
                paths,
                manifest,
                stage_key,
                [output],
                AnalysisStatus.ANALYZING,
                AnalysisStage.TREND_ANALYSIS,
                85,
            )
            return result

        logger.info("Checking for an earlier completed pulse to measure change.")
        await self._start_stage(
            job,
            paths,
            manifest,
            stage_key,
            AnalysisStatus.ANALYZING,
            AnalysisStage.TREND_ANALYSIS,
            81,
        )
        previous = await self.repository.previous_completed_analysis(
            project_id=job.project_id,
            before_analysis_run_id=job.analysis_run_id,
        )
        if previous is None or not previous.final_result_path:
            result = TrendResult(
                skipped_reason="This is the project's first completed Pulse."
            )
        else:
            previous_path = self.store.resolve_relative(previous.final_result_path)
            previous_result = self.store.read_json(previous_path)
            trend_context = _build_trend_context(
                previous_result.get("aggregation", {}), aggregation
            )
            generated = await self.llm.generate_structured(
                stage=stage_key,
                model=self.settings.analyzer_narrative_model,
                fallback_models=self.settings.analyzer_fallback_model_list,
                system_prompt=evidence_system_prompt("trend and momentum analysis"),
                user_prompt=structured_context_prompt(
                    {
                        "previous_analysis_run_id": str(previous.id),
                        "calculated_changes": trend_context,
                        "current_selected_evidence": evidence,
                    },
                    "Interpret only meaningful increases, decreases, appearances, "
                    "disappearances, and direction changes. Do not restate "
                    "every delta.",
                ),
                response_model=TrendResult,
            )
            result = generated.value.model_copy(
                update={"comparison_analysis_run_id": previous.id}
            )
            validate_evidence_ids(result, valid_ids)
            manifest.model_usage.append(generated.usage)
        self.store.write_json(output, result)
        await self._complete_stage(
            job,
            paths,
            manifest,
            stage_key,
            [output],
            AnalysisStatus.ANALYZING,
            AnalysisStage.TREND_ANALYSIS,
            85,
        )
        return result

    async def _synthesis(
        self,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
        aggregation: AggregationResult,
        themes: ThemeResult,
        asset_talent: AssetTalentResult,
        narrative: NarrativeSignalResult,
        trends: TrendResult,
        evidence: list[dict[str, Any]],
        valid_ids: set[uuid.UUID],
    ) -> SynthesisResult:
        if not valid_ids:
            result = SynthesisResult(
                recommendations=[],
                executive_pulse=ExecutivePulseResult(
                    campaign_health="Insufficient audience data",
                    what_is_working=[],
                    what_is_not_working=[],
                    what_changed=[],
                    watch_items=[],
                    next_actions=[
                        "Collect more audience conversation before interpretation."
                    ],
                    summary=(
                        "No audience mentions were available for this "
                        "collection run."
                    ),
                ),
            )
            output = paths.stages / "07_synthesis" / "result.json"
            self.store.write_json(output, result)
            await self._complete_stage(
                job,
                paths,
                manifest,
                "synthesis",
                [output],
                AnalysisStatus.SYNTHESIZING,
                AnalysisStage.SYNTHESIS,
                95,
            )
            return result

        logger.info("Creating strategic recommendations and the Executive Pulse.")
        return await self._structured_stage(
            job=job,
            paths=paths,
            manifest=manifest,
            key="synthesis",
            directory="07_synthesis",
            stage=AnalysisStage.SYNTHESIS,
            status=AnalysisStatus.SYNTHESIZING,
            start_progress=86,
            end_progress=95,
            model=self.settings.analyzer_synthesis_model,
            responsibility="strategic recommendation and executive synthesis",
            task=(
                "Produce concise recommendations in observation → interpretation → "
                "opportunity/risk → action form. Then produce an Executive Pulse "
                "answering campaign health, what works, what does not, what changed, "
                "what to watch, and what to do next. Synthesize existing findings; "
                "do not create a new independent analysis."
            ),
            context={
                "aggregates": aggregation.model_dump(mode="json"),
                "themes": themes.model_dump(mode="json"),
                "asset_and_talent": asset_talent.model_dump(mode="json"),
                "narratives_and_signals": narrative.model_dump(mode="json"),
                "trends": trends.model_dump(mode="json"),
                "selected_evidence": evidence,
            },
            response_model=SynthesisResult,
            valid_ids=valid_ids,
        )

    async def _structured_stage(
        self,
        *,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
        key: str,
        directory: str,
        stage: AnalysisStage,
        status: AnalysisStatus,
        start_progress: int,
        end_progress: int,
        model: str,
        responsibility: str,
        task: str,
        context: dict[str, Any],
        response_model: type[T],
        valid_ids: set[uuid.UUID],
    ) -> T:
        output = paths.stages / directory / "result.json"
        if output.exists():
            result = response_model.model_validate(self.store.read_json(output))
            validate_evidence_ids(result, valid_ids)
        else:
            await self._start_stage(
                job,
                paths,
                manifest,
                key,
                status,
                stage,
                start_progress,
            )
            generated = await self.llm.generate_structured(
                stage=key,
                model=model,
                fallback_models=self.settings.analyzer_fallback_model_list,
                system_prompt=evidence_system_prompt(responsibility),
                user_prompt=structured_context_prompt(context, task),
                response_model=response_model,
            )
            result = generated.value
            validate_evidence_ids(result, valid_ids)
            self.store.write_json(output, result)
            manifest.model_usage.append(generated.usage)
        await self._complete_stage(
            job,
            paths,
            manifest,
            key,
            [output],
            status,
            stage,
            end_progress,
        )
        return result

    async def _persist_empty_insight_stages(
        self,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
        themes: ThemeResult,
        asset_talent: AssetTalentResult,
        narrative: NarrativeSignalResult,
    ) -> None:
        values = [
            ("themes", "03_themes", themes, AnalysisStage.THEME_ANALYSIS, 60),
            (
                "asset_talent",
                "04_asset_talent",
                asset_talent,
                AnalysisStage.ASSET_TALENT_ANALYSIS,
                70,
            ),
            (
                "narratives_signals",
                "05_narratives_signals",
                narrative,
                AnalysisStage.NARRATIVE_SIGNAL_ANALYSIS,
                80,
            ),
        ]
        for key, directory, value, stage, progress in values:
            output = paths.stages / directory / "result.json"
            if not output.exists():
                self.store.write_json(output, value)
            await self._complete_stage(
                job,
                paths,
                manifest,
                key,
                [output],
                AnalysisStatus.ANALYZING,
                stage,
                progress,
            )

    async def _finalize(
        self,
        *,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
        project: dict[str, Any],
        collection: dict[str, Any],
        aggregation: AggregationResult,
        themes: ThemeResult,
        asset_talent: AssetTalentResult,
        narrative: NarrativeSignalResult,
        trends: TrendResult,
        synthesis: SynthesisResult,
        snapshots: list[MentionSnapshot],
    ) -> Path:
        logger.info(
            "Writing the final structured Pulse, evidence, and executive files."
        )
        final_path = paths.final / "audience_pulse.json"
        executive_path = paths.final / "executive_pulse.md"
        evidence_path = paths.final / "evidence.jsonl"
        usage_path = paths.final / "model_usage.json"
        final_payload = {
            "schema_version": 2,
            "analysis_run_id": str(job.analysis_run_id),
            "collection_run_id": str(job.collection_run_id),
            "collection_run_ids": [str(item) for item in job.collection_run_ids],
            "project_id": str(job.project_id),
            "project_title": project["title"],
            "analyzer_version": manifest.analyzer_version,
            "prompt_bundle_version": manifest.prompt_bundle_version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mention_analysis_cache": {
                "hits": manifest.mention_cache_hits,
                "misses": manifest.mention_cache_misses,
            },
            "collection_summary": collection,
            "aggregation": aggregation.model_dump(mode="json"),
            "themes": themes.model_dump(mode="json"),
            "asset_talent": asset_talent.model_dump(mode="json"),
            "narratives_signals": narrative.model_dump(mode="json"),
            "trends": trends.model_dump(mode="json"),
            "recommendations": [
                item.model_dump(mode="json") for item in synthesis.recommendations
            ],
            "executive_pulse": synthesis.executive_pulse.model_dump(mode="json"),
        }
        sections: dict[str, BaseModel] = {
            "themes": themes,
            "asset_talent": asset_talent,
            "narratives_signals": narrative,
            "trends": trends,
            "synthesis": synthesis,
        }
        self.store.write_json(final_path, final_payload)
        self.store.write_text(
            executive_path,
            executive_markdown(project["title"], synthesis.executive_pulse),
        )
        self.store.write_jsonl(
            evidence_path,
            build_evidence_records(sections, snapshots),
        )
        self.store.write_json(
            usage_path,
            [item.model_dump(mode="json") for item in manifest.model_usage],
        )

        manifest.status = AnalysisStatus.COMPLETED.value
        manifest.current_stage = AnalysisStage.COMPLETED.value
        manifest.completed_at = datetime.now(timezone.utc)
        manifest.updated_at = manifest.completed_at
        manifest.error_message = None
        self.store.save_manifest(paths, manifest)
        final_relative = self.store.relative(final_path)
        executive_relative = self.store.relative(executive_path)
        await self.repository.mark_completed(
            job.analysis_run_id,
            final_result_path=final_relative,
            executive_report_path=executive_relative,
            model_usage=manifest.model_usage,
        )
        await self._publish(
            job,
            manifest,
            AnalysisStatus.COMPLETED,
            AnalysisStage.COMPLETED,
            100,
            final_result_path=final_relative,
            executive_report_path=executive_relative,
        )
        return final_path

    async def _start_stage(
        self,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
        key: str,
        status: AnalysisStatus,
        stage: AnalysisStage,
        progress: int,
    ) -> None:
        manifest.status = status.value
        manifest.current_stage = stage.value
        manifest.stages[key] = StageManifest(status="running")
        manifest.updated_at = datetime.now(timezone.utc)
        self.store.save_manifest(paths, manifest)
        await self.repository.mark_progress(
            job.analysis_run_id,
            status=status,
            stage=stage,
            progress_pct=progress,
            mention_count=manifest.input_mentions,
            processed_mention_count=manifest.completed_mentions,
            model_usage=manifest.model_usage,
        )
        await self._publish(job, manifest, status, stage, progress)

    async def _complete_stage(
        self,
        job: AnalysisJob,
        paths: RunPaths,
        manifest: AnalysisManifest,
        key: str,
        outputs: list[Path],
        status: AnalysisStatus,
        stage: AnalysisStage,
        progress: int,
    ) -> None:
        manifest.status = status.value
        manifest.current_stage = stage.value
        manifest.stages[key] = StageManifest(
            status="completed",
            output_paths=[self.store.relative(path) for path in outputs],
            completed_items=(
                manifest.completed_mentions if key == "mention_analysis" else 1
            ),
            completed_at=datetime.now(timezone.utc),
        )
        manifest.updated_at = datetime.now(timezone.utc)
        self.store.save_manifest(paths, manifest)
        await self.repository.mark_progress(
            job.analysis_run_id,
            status=status,
            stage=stage,
            progress_pct=progress,
            mention_count=manifest.input_mentions,
            processed_mention_count=manifest.completed_mentions,
            model_usage=manifest.model_usage,
        )
        await self._publish(job, manifest, status, stage, progress)

    @staticmethod
    def _stage_completed(manifest: AnalysisManifest, key: str) -> bool:
        value = manifest.stages.get(key)
        return value is not None and value.status == "completed"

    async def _publish(
        self,
        job: AnalysisJob,
        manifest: AnalysisManifest,
        status: AnalysisStatus,
        stage: AnalysisStage,
        progress: int,
        *,
        final_result_path: str | None = None,
        executive_report_path: str | None = None,
        error_message: str | None = None,
    ) -> None:
        if self.report_progress is None:
            return
        await self.report_progress(
            AnalysisProgressEvent(
                analysis_run_id=job.analysis_run_id,
                collection_run_id=job.collection_run_id,
                collection_run_ids=job.collection_run_ids,
                project_id=job.project_id,
                status=status,
                current_stage=stage,
                progress_pct=progress,
                processed_mentions=manifest.completed_mentions,
                total_mentions=manifest.input_mentions,
                manifest_path=self.store.relative(
                    self.store.paths(
                        project_id=job.project_id,
                        collection_run_id=job.collection_run_id,
                        analysis_run_id=job.analysis_run_id,
                    ).manifest
                ),
                final_result_path=final_result_path,
                executive_report_path=executive_report_path,
                error_message=error_message,
            )
        )


def _validate_partial_batch_ids(
    analyses: list[MentionAnalysis], expected_ids: set[uuid.UUID]
) -> None:
    actual = [item.mention_id for item in analyses]
    if len(actual) != len(set(actual)):
        raise ValueError(
            "Partial mention-analysis batch contains duplicate mention IDs"
        )
    unknown = set(actual) - expected_ids
    if unknown:
        raise ValueError(
            f"Partial mention-analysis batch contains unknown IDs: {unknown}"
        )


def _validate_batch_ids(
    analyses: list[MentionAnalysis], expected_ids: set[uuid.UUID]
) -> None:
    actual = [item.mention_id for item in analyses]
    if len(actual) != len(set(actual)):
        raise ValueError("Mention-analysis batch contains duplicate mention IDs")
    if set(actual) != expected_ids:
        missing = expected_ids - set(actual)
        unknown = set(actual) - expected_ids
        raise ValueError(
            f"Mention-analysis batch ID mismatch; missing={missing}, unknown={unknown}"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_input_checksums(input_directory: Path) -> None:
    checksum_path = input_directory / "checksums.json"
    if not checksum_path.exists():
        raise RuntimeError("Completed snapshot is missing checksums.json")
    import json

    expected = json.loads(checksum_path.read_text(encoding="utf-8"))
    for filename, checksum in expected.items():
        path = input_directory / filename
        if not path.exists() or _sha256(path) != checksum:
            raise RuntimeError(f"Immutable analysis input changed: {filename}")


def _build_trend_context(
    previous: dict[str, Any], current: AggregationResult
) -> dict[str, Any]:
    previous_sentiment = {
        item["key"]: float(item["percentage"])
        for item in previous.get("sentiment_distribution", [])
    }
    current_sentiment = distribution_map(current.sentiment_distribution)
    sentiment_deltas = {
        key: round(current_sentiment.get(key, 0) - previous_sentiment.get(key, 0), 2)
        for key in sorted(set(previous_sentiment) | set(current_sentiment))
    }
    previous_aspects = {
        item["aspect"]: item for item in previous.get("aspect_performance", [])
    }
    current_aspects = {
        item.aspect: item.model_dump() for item in current.aspect_performance
    }
    return {
        "sentiment_percentage_point_changes": sentiment_deltas,
        "previous_aspect_performance": previous_aspects,
        "current_aspect_performance": current_aspects,
    }
