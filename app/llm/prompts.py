import json
from typing import Any

from app.contracts.analysis import FilmAspect, MentionSnapshot


QUALITY_RULES = """
Muvion distinguishes three levels: audience observation, Muvion interpretation,
and Muvion recommendation. Never collapse them. Use only supplied evidence.
Never invent percentages, people, assets, events, or mention IDs. A valid empty
list is better than a forced finding. Every major finding must cite actual mention
IDs. Do not expose author identity.
""".strip()


MENTION_SYSTEM_PROMPT = f"""
You analyze film-campaign audience reactions. Analyze each original statement
directly, including Indian-language text, transliteration, slang, sarcasm, emoji,
and code-mixing. Do not translate before classification. An optional concise
normalized English meaning may accompany the original-language understanding.

Use only this aspect taxonomy:
{', '.join(item.value for item in FilmAspect)}.

Return exactly one analysis for every supplied mention_id. Lower-level results
must be compact, structured, factual, and contain no report prose.

{QUALITY_RULES}
""".strip()


def mention_prompt(mentions: list[MentionSnapshot]) -> str:
    payload = [
        {
            "mention_id": str(item.mention_id),
            "platform": item.platform,
            "record_type": item.record_type,
            "text": item.text,
            "asset_type": item.asset_type,
            "asset_title": item.asset_title,
        }
        for item in mentions
    ]
    return "Analyze every mention in this JSON array:\n" + json.dumps(
        payload, ensure_ascii=False
    )


def evidence_system_prompt(responsibility: str) -> str:
    return f"""
You are the {responsibility} stage of Muvion Audience Pulse. You receive computed
statistics and selected structured mention evidence—not an unrestricted raw
conversation. Interpret patterns without recalculating or inventing statistics.
Preserve the distinction between observation and interpretation.

{QUALITY_RULES}
""".strip()


def structured_context_prompt(context: dict[str, Any], task: str) -> str:
    return f"{task}\n\nInput JSON:\n" + json.dumps(
        context, ensure_ascii=False, default=str
    )
