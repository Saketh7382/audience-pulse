import uuid
from collections import defaultdict
from typing import Any

from pydantic import BaseModel

from app.contracts.analysis import MentionAnalysis, MentionSnapshot


def select_evidence(
    snapshots: list[MentionSnapshot],
    analyses: list[MentionAnalysis],
    *,
    limit: int = 250,
) -> list[dict[str, Any]]:
    """Select a bounded, diverse evidence set for higher-level LLM stages.

    The selector prioritizes engaged and confidently understood mentions while
    round-robining sentiment/platform/aspect groups. This prevents a large source
    or a single dominant sentiment from consuming the entire context window.
    """
    snapshot_by_id = {item.mention_id: item for item in snapshots}
    groups: dict[tuple[str, str, str], list[MentionAnalysis]] = defaultdict(list)
    for item in analyses:
        snapshot = snapshot_by_id[item.mention_id]
        aspects = item.aspects or [None]
        for aspect in aspects:
            key = (
                snapshot.platform,
                item.sentiment.value,
                aspect.aspect.value if aspect else "no_aspect",
            )
            groups[key].append(item)

    for items in groups.values():
        items.sort(
            key=lambda item: (
                -_engagement(snapshot_by_id[item.mention_id]),
                -item.confidence,
                str(item.mention_id),
            )
        )

    selected: list[MentionAnalysis] = []
    selected_ids: set[uuid.UUID] = set()
    ordered_groups = [groups[key] for key in sorted(groups)]
    offset = 0
    while len(selected) < limit:
        added = False
        for items in ordered_groups:
            if offset >= len(items):
                continue
            candidate = items[offset]
            if candidate.mention_id not in selected_ids:
                selected.append(candidate)
                selected_ids.add(candidate.mention_id)
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        offset += 1

    return [
        {
            "mention_id": str(item.mention_id),
            "asset_id": str(snapshot_by_id[item.mention_id].asset_id),
            "platform": snapshot_by_id[item.mention_id].platform,
            "asset_type": snapshot_by_id[item.mention_id].asset_type,
            "asset_title": snapshot_by_id[item.mention_id].asset_title,
            "text": snapshot_by_id[item.mention_id].text,
            "analysis": item.model_dump(mode="json"),
        }
        for item in selected
    ]


def validate_evidence_ids(value: BaseModel, valid_ids: set[uuid.UUID]) -> None:
    """Reject LLM findings that cite invented or out-of-run mention IDs."""
    for mention_id in _find_evidence_ids(value.model_dump(mode="python")):
        if mention_id not in valid_ids:
            raise ValueError(f"Analysis cited unknown mention ID {mention_id}")


def build_evidence_records(
    sections: dict[str, BaseModel],
    snapshots: list[MentionSnapshot],
) -> list[dict[str, Any]]:
    snapshot_by_id = {item.mention_id: item for item in snapshots}
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, uuid.UUID]] = set()
    for section_name, section in sections.items():
        for finding_path, mention_ids in _finding_evidence(
            section.model_dump(mode="python"), section_name
        ):
            for mention_id in mention_ids:
                key = (finding_path, mention_id)
                if key in seen or mention_id not in snapshot_by_id:
                    continue
                seen.add(key)
                item = snapshot_by_id[mention_id]
                records.append(
                    {
                        "finding": finding_path,
                        "mention_id": str(item.mention_id),
                        "platform": item.platform,
                        "asset_id": str(item.asset_id),
                        "asset_type": item.asset_type,
                        "asset_title": item.asset_title,
                        "asset_url": item.asset_url,
                        "text": item.text,
                    }
                )
    return records


def _engagement(snapshot: MentionSnapshot) -> float:
    score = 0.0
    for key in ("like_count", "likes", "reply_count", "replies", "score"):
        value = snapshot.metrics.get(key)
        if isinstance(value, (int, float)):
            score += max(float(value), 0)
    return score


def _find_evidence_ids(value: Any) -> list[uuid.UUID]:
    result: list[uuid.UUID] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "supporting_mention_ids" and isinstance(child, list):
                result.extend(uuid.UUID(str(item)) for item in child)
            else:
                result.extend(_find_evidence_ids(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(_find_evidence_ids(child))
    return result


def _finding_evidence(value: Any, path: str):
    if isinstance(value, dict):
        ids = value.get("supporting_mention_ids")
        if isinstance(ids, list):
            name = value.get("name") or value.get("entity") or "finding"
            yield f"{path}.{name}", [uuid.UUID(str(item)) for item in ids]
        for key, child in value.items():
            if key != "supporting_mention_ids":
                yield from _finding_evidence(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _finding_evidence(child, f"{path}[{index}]")
