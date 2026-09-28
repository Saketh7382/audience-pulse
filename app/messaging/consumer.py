import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from app.contracts.jobs import AnalysisJob

logger = logging.getLogger(__name__)
AnalysisHandler = Callable[[AnalysisJob], Awaitable[object]]


class RedisAnalysisConsumer:
    """At-least-once Redis Streams consumer with safe crash recovery."""

    def __init__(
        self,
        client: Redis,
        *,
        stream: str,
        group: str,
        consumer_name: str,
        dead_letter_stream: str,
        stream_maxlen: int,
        block_ms: int,
        batch_size: int,
        pending_idle_ms: int,
        max_delivery_attempts: int,
        handler: AnalysisHandler,
    ) -> None:
        self.client = client
        self.stream = stream
        self.group = group
        self.consumer_name = consumer_name
        self.dead_letter_stream = dead_letter_stream
        self.stream_maxlen = stream_maxlen
        self.block_ms = block_ms
        self.batch_size = batch_size
        self.pending_idle_ms = pending_idle_ms
        self.max_delivery_attempts = max_delivery_attempts
        self.handler = handler

    async def ensure_consumer_group(self) -> None:
        try:
            await self.client.xgroup_create(
                self.stream, self.group, id="0-0", mkstream=True
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def consume_once(self) -> int:
        entries = await self.client.xreadgroup(
            groupname=self.group,
            consumername=self.consumer_name,
            streams={self.stream: ">"},
            count=self.batch_size,
            block=self.block_ms,
        )
        return await self._process_entries(entries)

    async def reclaim_once(self) -> int:
        claimed = await self.client.xautoclaim(
            self.stream,
            self.group,
            self.consumer_name,
            min_idle_time=self.pending_idle_ms,
            start_id="0-0",
            count=self.batch_size,
        )
        messages = claimed[1] if len(claimed) > 1 else []
        processed = 0
        for message_id, fields in messages:
            delivery_count = await self._delivery_count(str(message_id))
            if await self._process_message(
                str(message_id), fields, delivery_count=delivery_count
            ):
                processed += 1
        return processed

    async def run_forever(self) -> None:
        await self.ensure_consumer_group()
        logger.info("Audience Pulse worker is ready and waiting for analysis jobs.")
        while True:
            await self.reclaim_once()
            await self.consume_once()

    async def unregister_if_idle(self) -> bool:
        consumers = await self.client.xinfo_consumers(self.stream, self.group)
        target = next(
            (
                item
                for item in consumers
                if item.get("name") == self.consumer_name
                or item.get(b"name") == self.consumer_name.encode()
            ),
            None,
        )
        if target is None:
            return False
        if int(target.get("pending", target.get(b"pending", 0))):
            return False
        await self.client.xgroup_delconsumer(
            self.stream, self.group, self.consumer_name
        )
        return True

    async def _process_entries(self, entries) -> int:
        processed = 0
        for _, messages in entries:
            for message_id, fields in messages:
                if await self._process_message(str(message_id), fields):
                    processed += 1
        return processed

    async def _process_message(
        self,
        message_id: str,
        fields: dict[str, str],
        *,
        delivery_count: int = 1,
    ) -> bool:
        raw_payload = fields.get("payload")
        try:
            if raw_payload is None:
                raise ValueError("Redis message is missing the payload field")
            job = AnalysisJob.model_validate_json(raw_payload)
        except (ValidationError, ValueError) as exc:
            await self._dead_letter(message_id, raw_payload or "", str(exc))
            await self.client.xack(self.stream, self.group, message_id)
            logger.error("Invalid analysis job was moved to the dead-letter stream.")
            return False

        try:
            await self.handler(job)
        except Exception as exc:
            if delivery_count < self.max_delivery_attempts:
                logger.warning(
                    "Audience analysis paused at its latest completed checkpoint: "
                    "%s. The worker will retry it.",
                    exc,
                )
                return False
            await self._dead_letter(
                message_id,
                raw_payload,
                f"Delivery attempts exhausted ({delivery_count}): {exc}",
            )
            await self.client.xack(self.stream, self.group, message_id)
            logger.error("Analysis retries were exhausted; the job was dead-lettered.")
            return False

        await self.client.xack(self.stream, self.group, message_id)
        return True

    async def _delivery_count(self, message_id: str) -> int:
        pending = await self.client.xpending_range(
            self.stream,
            self.group,
            min=message_id,
            max=message_id,
            count=1,
        )
        if not pending:
            return 1
        item = pending[0]
        return int(item.get("times_delivered", item.get(b"times_delivered", 1)))

    async def _dead_letter(self, message_id: str, payload: str, error: str) -> None:
        await self.client.xadd(
            self.dead_letter_stream,
            {
                "source_stream": self.stream,
                "source_message_id": message_id,
                "payload": payload,
                "error": error,
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
            maxlen=self.stream_maxlen,
            approximate=True,
        )
