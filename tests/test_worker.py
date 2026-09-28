import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.worker import enqueue_run


@pytest.mark.asyncio
async def test_cli_requeues_same_failed_analysis_attempt(monkeypatch, tmp_path):
    project_id = uuid.uuid4()
    collection_run_id = uuid.uuid4()
    analysis_run_id = uuid.uuid4()
    existing = SimpleNamespace(id=analysis_run_id, status="failed")

    class FakeDatabase:
        def __init__(self, database_url):
            self.sessions = object()
            self.close = AsyncMock()

    class FakeRepository:
        def __init__(self, sessions):
            self.reset_failed_for_dispatch = AsyncMock()
            self.mark_failed = AsyncMock()

        async def collection_run_project_id(self, incoming_run_id):
            assert incoming_run_id == collection_run_id
            return project_id

        async def get_by_collection_run(self, incoming_run_id):
            assert incoming_run_id == collection_run_id
            return existing

    redis = SimpleNamespace(xadd=AsyncMock(return_value="1-0"), aclose=AsyncMock())
    repository = FakeRepository(object())
    monkeypatch.setattr("app.worker.Database", FakeDatabase)
    monkeypatch.setattr("app.worker.AnalysisRepository", lambda sessions: repository)
    monkeypatch.setattr("app.worker.Redis.from_url", lambda *args, **kwargs: redis)
    settings = Settings(analyzer_storage_root=tmp_path)

    result = await enqueue_run(settings, collection_run_id=collection_run_id)

    assert result == analysis_run_id
    repository.reset_failed_for_dispatch.assert_awaited_once_with(analysis_run_id)
    payload = json.loads(redis.xadd.await_args.args[1]["payload"])
    assert payload["analysis_run_id"] == str(analysis_run_id)
    assert payload["collection_run_id"] == str(collection_run_id)
    assert payload["collection_run_ids"] == [str(collection_run_id)]
    assert payload["schema_version"] == 2
    redis.aclose.assert_awaited_once()
