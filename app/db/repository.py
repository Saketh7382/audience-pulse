import hashlib
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.analysis import MentionSnapshot, ModelUsageEntry
from app.contracts.jobs import AnalysisStage, AnalysisStatus
from app.db.models import AnalysisRun, AnalysisRunCollectionRun


class AnalysisInputError(RuntimeError):
    pass


class AnalysisRepository:
    """Lifecycle metadata and immutable-input reads from the shared database."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def create(
        self,
        *,
        analysis_run_id: uuid.UUID,
        project_id: uuid.UUID,
        collection_run_id: uuid.UUID,
        collection_run_ids: list[uuid.UUID] | None = None,
        manifest_path: str,
        analyzer_version: str,
        prompt_bundle_version: str,
    ) -> AnalysisRun:
        run_ids = canonical_run_ids(collection_run_ids or [collection_run_id])
        async with self.sessions() as session:
            for run_id in run_ids:
                await self._validate_collection_run(
                    session,
                    project_id=project_id,
                    collection_run_id=run_id,
                )
            row = AnalysisRun(
                id=analysis_run_id,
                project_id=project_id,
                collection_run_id=run_ids[0],
                input_signature=input_signature(run_ids),
                manifest_path=manifest_path,
                analyzer_version=analyzer_version,
                prompt_bundle_version=prompt_bundle_version,
            )
            session.add(row)
            session.add_all(
                AnalysisRunCollectionRun(
                    analysis_run_id=analysis_run_id,
                    collection_run_id=run_id,
                    position=position,
                )
                for position, run_id in enumerate(run_ids)
            )
            await session.commit()
            await session.refresh(row)
            row._collection_run_ids = run_ids
            return row

    async def get(self, analysis_run_id: uuid.UUID) -> AnalysisRun | None:
        async with self.sessions() as session:
            row = await session.get(AnalysisRun, analysis_run_id)
            if row is not None:
                await self._load_collection_run_ids(session, row)
            return row

    async def get_by_input_signature(
        self, project_id: uuid.UUID, run_ids: list[uuid.UUID]
    ) -> AnalysisRun | None:
        signature = input_signature(canonical_run_ids(run_ids))
        async with self.sessions() as session:
            row = await session.scalar(
                select(AnalysisRun).where(
                    AnalysisRun.project_id == project_id,
                    AnalysisRun.input_signature == signature,
                )
            )
            if row is not None:
                await self._load_collection_run_ids(session, row)
            return row

    async def get_by_collection_run(
        self, collection_run_id: uuid.UUID
    ) -> AnalysisRun | None:
        """Compatibility lookup for CLI callers that enqueue one run."""
        project_id = await self.collection_run_project_id(collection_run_id)
        exact = await self.get_by_input_signature(project_id, [collection_run_id])
        if exact is not None:
            return exact
        async with self.sessions() as session:
            return await session.scalar(
                select(AnalysisRun)
                .join(
                    AnalysisRunCollectionRun,
                    AnalysisRunCollectionRun.analysis_run_id == AnalysisRun.id,
                )
                .where(
                    AnalysisRun.project_id == project_id,
                    AnalysisRunCollectionRun.collection_run_id == collection_run_id,
                )
                .group_by(AnalysisRun.id)
                .having(func.count(AnalysisRunCollectionRun.collection_run_id) == 1)
                .order_by(AnalysisRun.created_at.desc())
                .limit(1)
            )

    async def reset_failed_for_dispatch(self, analysis_run_id: uuid.UUID) -> None:
        async with self.sessions() as session:
            row = await session.get(AnalysisRun, analysis_run_id, with_for_update=True)
            if row is None:
                raise AnalysisInputError(
                    f"Analysis run {analysis_run_id} was not found"
                )
            if row.status != AnalysisStatus.FAILED.value:
                return
            row.status = AnalysisStatus.QUEUED.value
            row.current_stage = AnalysisStage.INITIALIZING.value
            row.progress_pct = 0
            row.error_message = None
            row.completed_at = None
            await session.commit()

    async def mark_progress(
        self,
        analysis_run_id: uuid.UUID,
        *,
        status: AnalysisStatus,
        stage: AnalysisStage,
        progress_pct: int,
        mention_count: int | None = None,
        processed_mention_count: int | None = None,
        model_usage: list[ModelUsageEntry] | None = None,
    ) -> None:
        async with self.sessions() as session:
            row = await session.get(AnalysisRun, analysis_run_id, with_for_update=True)
            if row is None:
                raise AnalysisInputError(
                    f"Analysis run {analysis_run_id} was not found"
                )
            row.status = status.value
            row.current_stage = stage.value
            row.progress_pct = progress_pct
            if row.started_at is None:
                row.started_at = datetime.now(timezone.utc)
            if mention_count is not None:
                row.mention_count = mention_count
            if processed_mention_count is not None:
                row.processed_mention_count = processed_mention_count
            if model_usage is not None:
                row.model_usage = [item.model_dump(mode="json") for item in model_usage]
            await session.commit()

    async def mark_completed(
        self,
        analysis_run_id: uuid.UUID,
        *,
        final_result_path: str,
        executive_report_path: str,
        model_usage: list[ModelUsageEntry],
    ) -> None:
        async with self.sessions() as session:
            row = await session.get(AnalysisRun, analysis_run_id, with_for_update=True)
            if row is None:
                raise AnalysisInputError(
                    f"Analysis run {analysis_run_id} was not found"
                )
            row.status = AnalysisStatus.COMPLETED.value
            row.current_stage = AnalysisStage.COMPLETED.value
            row.progress_pct = 100
            row.processed_mention_count = row.mention_count
            row.final_result_path = final_result_path
            row.executive_report_path = executive_report_path
            row.model_usage = [item.model_dump(mode="json") for item in model_usage]
            row.completed_at = datetime.now(timezone.utc)
            row.error_message = None
            await session.commit()

    async def mark_failed(self, analysis_run_id: uuid.UUID, error: str) -> None:
        async with self.sessions() as session:
            row = await session.get(AnalysisRun, analysis_run_id, with_for_update=True)
            if row is None:
                return
            if row.status == AnalysisStatus.COMPLETED.value:
                return
            row.status = AnalysisStatus.FAILED.value
            row.current_stage = AnalysisStage.FAILED.value
            row.error_message = error[:4000]
            row.completed_at = datetime.now(timezone.utc)
            await session.commit()

    async def collection_run_project_id(
        self, collection_run_id: uuid.UUID
    ) -> uuid.UUID:
        async with self.sessions() as session:
            project_id = (
                await session.execute(
                    text("SELECT project_id FROM project_runs WHERE id = :run_id"),
                    {"run_id": collection_run_id},
                )
            ).scalar_one_or_none()
            if project_id is None:
                raise AnalysisInputError(
                    f"Collection run {collection_run_id} was not found"
                )
            return project_id

    async def project_snapshot(self, project_id: uuid.UUID) -> dict[str, Any]:
        async with self.sessions() as session:
            project = (
                (
                    await session.execute(
                        text(
                            "SELECT id, title, release_date, campaign_start_date, "
                            "entities, created_at, updated_at FROM projects "
                            "WHERE id = :id"
                        ),
                        {"id": project_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if project is None:
                raise AnalysisInputError(f"Project {project_id} was not found")

            assets = (
                (
                    await session.execute(
                        text(
                            "SELECT id, channel, asset_type, url FROM project_assets "
                            "WHERE project_id = :id ORDER BY created_at, id"
                        ),
                        {"id": project_id},
                    )
                )
                .mappings()
                .all()
            )
            sources = (
                (
                    await session.execute(
                        text(
                            "SELECT id, platform, source_type, source_identifier, url, "
                            "display_name, is_official FROM project_sources "
                            "WHERE project_id = :id AND is_active = true "
                            "ORDER BY created_at, id"
                        ),
                        {"id": project_id},
                    )
                )
                .mappings()
                .all()
            )
            connectors = (
                (
                    await session.execute(
                        text(
                            "SELECT connector_key, is_enabled FROM project_connectors "
                            "WHERE project_id = :id ORDER BY connector_key"
                        ),
                        {"id": project_id},
                    )
                )
                .mappings()
                .all()
            )
            return {
                **_json_mapping(project),
                "target_assets": [_json_mapping(item) for item in assets],
                "sources": [_json_mapping(item) for item in sources],
                # Provider credentials and scraper settings are intentionally not
                # copied into analysis files; Analyzer needs identity, not secrets.
                "connectors": [_json_mapping(item) for item in connectors],
            }

    async def collection_summary(self, collection_run_id: uuid.UUID) -> dict[str, Any]:
        async with self.sessions() as session:
            run = (
                (
                    await session.execute(
                        text(
                            "SELECT id, project_id, status, active_channels, "
                            "collection_since, collection_until, triggered_at, "
                            "completed_at "
                            "FROM project_runs WHERE id = :run_id"
                        ),
                        {"run_id": collection_run_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if run is None:
                raise AnalysisInputError(
                    f"Collection run {collection_run_id} was not found"
                )
            counts = (
                (
                    await session.execute(
                        text(
                            "SELECT m.platform, rm.collection_tier, count(*) "
                            "AS mentions "
                            "FROM run_mentions rm JOIN mentions m "
                            "ON m.id = rm.mention_id "
                            "WHERE rm.run_id = :run_id "
                            "GROUP BY m.platform, rm.collection_tier "
                            "ORDER BY m.platform, rm.collection_tier"
                        ),
                        {"run_id": collection_run_id},
                    )
                )
                .mappings()
                .all()
            )
            return {
                **_json_mapping(run),
                "mention_counts": [_json_mapping(item) for item in counts],
            }

    async def mentions(self, collection_run_id: uuid.UUID) -> list[MentionSnapshot]:
        async with self.sessions() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT m.id AS mention_id, m.asset_id, m.platform, "
                            "m.record_type, m.text, m.published_at, m.metrics, "
                            "rm.collection_tier, ha.asset_type, "
                            "ha.title AS asset_title, "
                            "ha.url AS asset_url, ha.source_name "
                            "FROM run_mentions rm "
                            "JOIN mentions m ON m.id = rm.mention_id "
                            "JOIN harvested_assets ha ON ha.id = m.asset_id "
                            "WHERE rm.run_id = :run_id "
                            "ORDER BY m.published_at, m.id"
                        ),
                        {"run_id": collection_run_id},
                    )
                )
                .mappings()
                .all()
            )
        return [MentionSnapshot.model_validate(dict(row)) for row in rows]

    async def previous_completed_analysis(
        self,
        *,
        project_id: uuid.UUID,
        before_analysis_run_id: uuid.UUID,
    ) -> AnalysisRun | None:
        async with self.sessions() as session:
            current = await session.get(AnalysisRun, before_analysis_run_id)
            if current is None:
                return None
            statement = (
                select(AnalysisRun)
                .where(
                    AnalysisRun.project_id == project_id,
                    AnalysisRun.status == AnalysisStatus.COMPLETED.value,
                    AnalysisRun.created_at < current.created_at,
                )
                .order_by(AnalysisRun.created_at.desc())
                .limit(1)
            )
            return (await session.execute(statement)).scalar_one_or_none()

    @staticmethod
    async def _load_collection_run_ids(session: AsyncSession, row: AnalysisRun) -> None:
        row._collection_run_ids = list(
            (
                await session.scalars(
                    select(AnalysisRunCollectionRun.collection_run_id)
                    .where(AnalysisRunCollectionRun.analysis_run_id == row.id)
                    .order_by(AnalysisRunCollectionRun.position)
                )
            ).all()
        )

    @staticmethod
    async def _validate_collection_run(
        session: AsyncSession,
        *,
        project_id: uuid.UUID,
        collection_run_id: uuid.UUID,
    ) -> None:
        result = (
            (
                await session.execute(
                    text(
                        "SELECT pr.status, "
                        "count(*) FILTER (WHERE t.status <> 'completed') AS incomplete "
                        "FROM project_runs pr "
                        "LEFT JOIN project_run_tasks t ON t.run_id = pr.id "
                        "WHERE pr.id = :run_id AND pr.project_id = :project_id "
                        "GROUP BY pr.status"
                    ),
                    {"run_id": collection_run_id, "project_id": project_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if result is None:
            raise AnalysisInputError(
                f"Collection run {collection_run_id} was not found for "
                f"project {project_id}"
            )
        if int(result["incomplete"] or 0) > 0:
            raise AnalysisInputError(
                "Analysis cannot start until every requested connector task completes"
            )


def _json_mapping(value: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in dict(value).items():
        if isinstance(item, uuid.UUID):
            result[key] = str(item)
        elif isinstance(item, (date, datetime)):
            result[key] = item.isoformat()
        else:
            result[key] = item
    return result


def canonical_run_ids(run_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    if not run_ids:
        raise AnalysisInputError("At least one collection run is required")
    if len(set(run_ids)) != len(run_ids):
        raise AnalysisInputError("Collection run IDs must not contain duplicates")
    return sorted(run_ids, key=str)


def input_signature(run_ids: list[uuid.UUID]) -> str:
    payload = ",".join(str(item) for item in run_ids).encode("ascii")
    return hashlib.sha256(payload).hexdigest()
