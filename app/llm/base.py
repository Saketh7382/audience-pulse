from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.contracts.analysis import ModelUsageEntry

T = TypeVar("T", bound=BaseModel)


class GenerationResult(BaseModel, Generic[T]):
    value: T
    usage: ModelUsageEntry


class StructuredLLMProvider(ABC):
    """Provider-neutral contract for one schema-validated model generation."""

    @abstractmethod
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
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError
