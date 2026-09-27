import json
import logging
from datetime import datetime
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).astimezone().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str, output_format: str) -> None:
    handler = logging.StreamHandler()
    if output_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # INFO is reserved for the human-readable analysis lifecycle. Dependency
    # details remain available when the service itself runs at DEBUG.
    for dependency in ("httpx", "httpcore", "redis", "sqlalchemy", "asyncio"):
        logging.getLogger(dependency).setLevel(logging.WARNING)

