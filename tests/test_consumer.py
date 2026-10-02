import uuid

import pytest

from app.contracts.jobs import AnalysisJob
from app.messaging.consumer import RedisAnalysisConsumer


class FakeRedis:
    def __init__(self):
        self.acked = []
        self.dead_letters = []

    async def xack(self, stream, group, message_id):
        self.acked.append((stream, group, message_id))

    async def xadd(self, stream, fields, **values):
        self.dead_letters.append((stream, fields))
        return "1-0"


def consumer(redis, handler, attempts=3, dead_letter_handler=None):
    return RedisAnalysisConsumer(
        redis,
        stream="jobs",
        group="workers",
        consumer_name="test",
        dead_letter_stream="dead",
        stream_maxlen=100,
        block_ms=1,
        batch_size=1,
        pending_idle_ms=1,
        max_delivery_attempts=attempts,
        handler=handler,
        dead_letter_handler=dead_letter_handler,
    )


@pytest.mark.asyncio
async def test_successful_job_is_acknowledged():
    redis = FakeRedis()
    handled = []

    async def handler(job):
        handled.append(job)

    job = AnalysisJob(
        analysis_run_id=uuid.uuid4(),
        collection_run_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
    )
    result = await consumer(redis, handler)._process_message(
        "1-0", {"payload": job.model_dump_json()}
    )

    assert result is True
    assert handled == [job]
    assert redis.acked == [("jobs", "workers", "1-0")]
    assert redis.dead_letters == []


@pytest.mark.asyncio
async def test_failed_job_stays_pending_until_attempts_are_exhausted():
    redis = FakeRedis()

    async def handler(job):
        raise RuntimeError("provider unavailable")

    job = AnalysisJob(
        analysis_run_id=uuid.uuid4(),
        collection_run_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
    )
    target = consumer(redis, handler, attempts=3)

    retry_result = await target._process_message(
        "1-0", {"payload": job.model_dump_json()}, delivery_count=1
    )
    terminal_result = await target._process_message(
        "1-0", {"payload": job.model_dump_json()}, delivery_count=3
    )

    assert retry_result is False
    assert terminal_result is False
    assert redis.acked == [("jobs", "workers", "1-0")]
    assert redis.dead_letters[0][0] == "dead"


@pytest.mark.asyncio
async def test_invalid_job_is_dead_lettered_and_acknowledged():
    redis = FakeRedis()

    async def handler(job):
        raise AssertionError("invalid jobs must not reach handler")

    result = await consumer(redis, handler)._process_message(
        "bad-1", {"payload": "not-json"}
    )

    assert result is False
    assert redis.acked == [("jobs", "workers", "bad-1")]
    assert redis.dead_letters[0][0] == "dead"


@pytest.mark.asyncio
async def test_dead_letter_callback_runs_before_message_acknowledgement():
    redis = FakeRedis()
    reconciled = []

    async def handler(job):
        raise RuntimeError("permanent provider failure")

    async def dead_letter_handler(payload, error):
        # The callback observes no ACK yet, so a failed database reconciliation
        # cannot silently lose the Redis job.
        assert redis.acked == []
        reconciled.append((payload, error))

    job = AnalysisJob(
        analysis_run_id=uuid.uuid4(),
        collection_run_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
    )
    target = consumer(
        redis, handler, attempts=2, dead_letter_handler=dead_letter_handler
    )

    await target._process_message(
        "2-0", {"payload": job.model_dump_json()}, delivery_count=2
    )

    assert len(reconciled) == 1
    assert str(job.analysis_run_id) in reconciled[0][0]
    assert "attempts exhausted" in reconciled[0][1]
    assert redis.acked == [("jobs", "workers", "2-0")]
