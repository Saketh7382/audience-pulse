import json
import logging
import os
import socket
import uuid

from redis.asyncio import Redis

from app.contracts.jobs import AnalysisJob
from app.core.config import Settings
from app.db.repository import AnalysisRepository
from app.db.session import Database
from app.llm.openrouter import OpenRouterProvider
from app.messaging.consumer import RedisAnalysisConsumer
from app.messaging.publisher import RedisAnalysisEventPublisher
from app.pipeline.orchestrator import AnalysisPipeline
from app.storage.local import LocalAnalysisStore

logger = logging.getLogger(__name__)


def consumer_name() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


class WorkerResources:
    def __init__(
        self,
        settings: Settings,
        redis: Redis | None = None,
        *,
        publish_events: bool = True,
    ) -> None:
        if settings.openrouter_api_key is None:
            raise RuntimeError("OPENROUTER_API_KEY is required to run analysis")
        self.settings = settings
        self.database = Database(settings.database_url)
        self.repository = AnalysisRepository(self.database.sessions)
        self.redis = redis or Redis.from_url(settings.redis_url, decode_responses=True)
        self._owns_redis = redis is None
        self.event_publisher = RedisAnalysisEventPublisher(
            self.redis,
            stream=settings.redis_analysis_event_stream,
            maxlen=settings.redis_stream_maxlen,
        )
        self.llm = OpenRouterProvider(
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            site_url=settings.openrouter_site_url,
            app_name=settings.openrouter_app_name,
            timeout_seconds=settings.openrouter_timeout_seconds,
            max_retries=settings.openrouter_max_retries,
            max_output_tokens=settings.openrouter_max_output_tokens,
        )
        self.pipeline = AnalysisPipeline(
            settings=settings,
            repository=self.repository,
            store=LocalAnalysisStore(settings.analyzer_storage_root),
            llm=self.llm,
            report_progress=(self.event_publisher.publish if publish_events else None),
        )

    def consumer(self) -> RedisAnalysisConsumer:
        return RedisAnalysisConsumer(
            self.redis,
            stream=self.settings.redis_analysis_job_stream,
            group=self.settings.redis_analysis_consumer_group,
            consumer_name=consumer_name(),
            dead_letter_stream=self.settings.redis_analysis_dead_letter_stream,
            stream_maxlen=self.settings.redis_stream_maxlen,
            block_ms=self.settings.redis_block_ms,
            batch_size=self.settings.redis_batch_size,
            pending_idle_ms=self.settings.redis_pending_idle_ms,
            max_delivery_attempts=self.settings.redis_max_delivery_attempts,
            handler=self.pipeline.run,
            dead_letter_handler=self._mark_dead_lettered,
        )

    async def _mark_dead_lettered(self, payload: str, error: str) -> None:
        """Keep database lifecycle state consistent with terminal Redis handling."""
        try:
            value = json.loads(payload)
            analysis_run_id = uuid.UUID(str(value["analysis_run_id"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            logger.error(
                "Dead-lettered analysis payload has no usable analysis_run_id."
            )
            return
        await self.repository.mark_failed(
            analysis_run_id, f"Analysis job dead-lettered: {error}"
        )

    async def close(self) -> None:
        await self.llm.close()
        await self.database.close()
        if self._owns_redis:
            await self.redis.aclose()


async def run_worker(settings: Settings, *, once: bool = False) -> None:
    resources = WorkerResources(settings)
    consumer = resources.consumer()
    try:
        if once:
            await consumer.ensure_consumer_group()
            await consumer.reclaim_once()
            await consumer.consume_once()
        else:
            await consumer.run_forever()
    finally:
        try:
            await consumer.unregister_if_idle()
        finally:
            await resources.close()


async def run_local(
    settings: Settings,
    *,
    collection_run_id: uuid.UUID,
    analysis_run_id: uuid.UUID | None = None,
) -> uuid.UUID:
    resources = WorkerResources(settings, publish_events=False)
    try:
        project_id = await resources.repository.collection_run_project_id(
            collection_run_id
        )
        resolved_analysis_id = analysis_run_id or uuid.uuid4()
        paths = resources.pipeline.store.paths(
            project_id=project_id,
            collection_run_id=collection_run_id,
            analysis_run_id=resolved_analysis_id,
        )
        existing = await resources.repository.get(resolved_analysis_id)
        if existing is None:
            await resources.repository.create(
                analysis_run_id=resolved_analysis_id,
                project_id=project_id,
                collection_run_id=collection_run_id,
                manifest_path=resources.pipeline.store.relative(paths.manifest),
                analyzer_version=settings.analyzer_version,
                prompt_bundle_version=settings.prompt_bundle_version,
            )
        await resources.pipeline.run(
            AnalysisJob(
                analysis_run_id=resolved_analysis_id,
                collection_run_id=collection_run_id,
                project_id=project_id,
            )
        )
        return resolved_analysis_id
    finally:
        await resources.close()


async def enqueue_run(
    settings: Settings,
    *,
    collection_run_id: uuid.UUID,
) -> uuid.UUID:
    """Create analysis metadata and publish the same job expected from Control Plane."""
    database = Database(settings.database_url)
    repository = AnalysisRepository(database.sessions)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    analysis_run_id: uuid.UUID | None = None
    try:
        project_id = await repository.collection_run_project_id(collection_run_id)
        existing = await repository.get_by_collection_run(collection_run_id)
        if existing is not None:
            analysis_run_id = existing.id
            if existing.status != "failed":
                return analysis_run_id
            await repository.reset_failed_for_dispatch(analysis_run_id)
        else:
            analysis_run_id = uuid.uuid4()
            store = LocalAnalysisStore(settings.analyzer_storage_root)
            paths = store.paths(
                project_id=project_id,
                collection_run_id=collection_run_id,
                analysis_run_id=analysis_run_id,
            )
            await repository.create(
                analysis_run_id=analysis_run_id,
                project_id=project_id,
                collection_run_id=collection_run_id,
                manifest_path=store.relative(paths.manifest),
                analyzer_version=settings.analyzer_version,
                prompt_bundle_version=settings.prompt_bundle_version,
            )
        job = AnalysisJob(
            analysis_run_id=analysis_run_id,
            collection_run_id=collection_run_id,
            project_id=project_id,
        )
        await redis.xadd(
            settings.redis_analysis_job_stream,
            {"payload": job.model_dump_json()},
            maxlen=settings.redis_stream_maxlen,
            approximate=True,
        )
        return analysis_run_id
    except Exception as exc:
        if analysis_run_id is not None:
            await repository.mark_failed(
                analysis_run_id, f"Unable to dispatch analysis job: {exc}"
            )
        raise
    finally:
        await database.close()
        await redis.aclose()
