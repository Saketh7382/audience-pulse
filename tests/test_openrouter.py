import json
import uuid

import httpx
import pytest

from app.contracts.analysis import MentionAnalysisBatch
from app.llm.openrouter import OpenRouterProvider


@pytest.mark.asyncio
async def test_openrouter_uses_models_fallback_and_validates_schema():
    mention_id = uuid.uuid4()

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["models"] == [
            "google/gemini-3.5-flash-lite",
            "openai/gpt-5-mini",
        ]
        assert payload["provider"]["require_parameters"] is True
        assert payload["response_format"]["type"] == "json_schema"
        result = {
            "analyses": [
                {
                    "mention_id": str(mention_id),
                    "language": "Telugu-English code-mixed",
                    "normalized_meaning_en": "The BGM is excellent.",
                    "sentiment": "positive",
                    "sentiment_strength": "strong",
                    "primary_emotion": "excitement",
                    "secondary_emotions": [],
                    "aspects": [],
                    "positive_points": ["BGM praised"],
                    "negative_points": [],
                    "audience_intent": "none",
                    "is_question": False,
                    "question_topic": None,
                    "comparisons": [],
                    "expectations": [],
                    "speculation": [],
                    "entities_discussed": [],
                    "confidence": 0.95,
                }
            ]
        }
        return httpx.Response(
            200,
            json={
                "id": "generation-1",
                "model": "google/gemini-3.5-flash-lite",
                "choices": [{"message": {"content": json.dumps(result)}}],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 30,
                    "total_tokens": 50,
                    "cost": 0.001,
                },
            },
        )

    client = httpx.AsyncClient(
        base_url="https://openrouter.test/api/v1",
        transport=httpx.MockTransport(handler),
    )
    provider = OpenRouterProvider(
        api_key="test-key",
        base_url="https://openrouter.test/api/v1",
        site_url="https://muvion.test",
        app_name="Muvion Test",
        timeout_seconds=10,
        max_retries=1,
        client=client,
    )
    generated = await provider.generate_structured(
        stage="mention_analysis",
        model="google/gemini-3.5-flash-lite",
        fallback_models=["openai/gpt-5-mini"],
        system_prompt="Analyze.",
        user_prompt="Input.",
        response_model=MentionAnalysisBatch,
    )

    assert generated.value.analyses[0].mention_id == mention_id
    assert generated.usage.total_tokens == 50
    assert generated.usage.cost_usd == 0.001
    await client.aclose()
