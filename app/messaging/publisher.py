from redis.asyncio import Redis

from app.contracts.jobs import AnalysisProgressEvent


class RedisAnalysisEventPublisher:
    def __init__(self, client: Redis, *, stream: str, maxlen: int) -> None:
        self.client = client
        self.stream = stream
        self.maxlen = maxlen

    async def publish(self, event: AnalysisProgressEvent) -> str:
        message_id = await self.client.xadd(
            self.stream,
            {"payload": event.model_dump_json()},
            maxlen=self.maxlen,
            approximate=True,
        )
        return str(message_id)
