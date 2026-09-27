import asyncio
import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.contracts.analysis import ModelUsageEntry
from app.llm.base import GenerationResult, StructuredLLMProvider

T = TypeVar("T", bound=BaseModel)


class OpenRouterError(RuntimeError):
    pass


class OpenRouterProvider(StructuredLLMProvider):
    """OpenRouter client using its OpenAI-compatible structured-output API.

    The primary and fallback model slugs are data, not code. OpenRouter first
    tries each upstream provider for the primary model and can then move through
    the configured model list. The actual serving model is captured in usage so
    every analysis remains auditable when a fallback is used.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        site_url: str,
        app_name: str,
        timeout_seconds: float,
        max_retries: int,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.max_retries = max_retries
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": site_url,
                "X-Title": app_name,
            },
        )

    async def generate_structured(
        self,
        *,
        stage: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        fallback_models: list[str] | None = None,
    ) -> GenerationResult[T]:
        models = list(dict.fromkeys([model, *(fallback_models or [])]))
        schema = response_model.model_json_schema()
        payload: dict[str, Any] = {
            "models": models,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__.lower(),
                    "strict": True,
                    "schema": schema,
                },
            },
            "provider": {"require_parameters": True},
        }

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self.client.post("/chat/completions", json=payload)
                response.raise_for_status()
                raw = response.json()
                content = raw["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    content = "".join(
                        item.get("text", "")
                        for item in content
                        if isinstance(item, dict)
                    )
                value = response_model.model_validate_json(content)
                usage = raw.get("usage") or {}
                return GenerationResult(
                    value=value,
                    usage=ModelUsageEntry(
                        stage=stage,
                        model=raw.get("model", model),
                        generation_id=raw.get("id"),
                        prompt_tokens=int(usage.get("prompt_tokens") or 0),
                        completion_tokens=int(usage.get("completion_tokens") or 0),
                        total_tokens=int(usage.get("total_tokens") or 0),
                        cost_usd=_optional_float(usage.get("cost")),
                    ),
                )
            except (
                httpx.HTTPError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
                ValidationError,
            ) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                await asyncio.sleep(min(2 ** (attempt - 1), 8))
        raise OpenRouterError(
            f"OpenRouter structured generation failed after {self.max_retries} attempts"
        ) from last_error

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
