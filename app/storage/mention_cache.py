import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from app.contracts.analysis import MentionAnalysis, MentionSnapshot, StrictModel
from app.storage.local import LocalAnalysisStore

logger = logging.getLogger(__name__)


class MentionCacheEntry(StrictModel):
    """One reusable mention result bound to its exact input and analysis contract."""

    schema_version: Literal[1] = 1
    mention_id: uuid.UUID
    input_fingerprint: str
    analyzer_version: str
    prompt_bundle_version: str
    requested_model: str
    analysis: MentionAnalysis
    cached_at: datetime


class MentionAnalysisCache:
    """Crash-safe file cache for the expensive per-mention LLM stage.

    The namespace changes whenever the analyzer, prompt bundle, or requested model
    changes. The input fingerprint additionally prevents reuse if an allegedly
    immutable mention is corrected in PostgreSQL.
    """

    def __init__(
        self,
        store: LocalAnalysisStore,
        *,
        analyzer_version: str,
        prompt_bundle_version: str,
        requested_model: str,
    ) -> None:
        self.store = store
        self.analyzer_version = analyzer_version
        self.prompt_bundle_version = prompt_bundle_version
        self.requested_model = requested_model
        namespace_payload = json.dumps(
            {
                "analyzer_version": analyzer_version,
                "prompt_bundle_version": prompt_bundle_version,
                "requested_model": requested_model,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self.namespace = hashlib.sha256(namespace_payload).hexdigest()[:24]

    def get(self, snapshot: MentionSnapshot) -> MentionAnalysis | None:
        path = self._path(snapshot.mention_id)
        if not path.exists():
            return None
        try:
            entry = MentionCacheEntry.model_validate(self.store.read_json(path))
        except (OSError, ValueError, ValidationError) as exc:
            logger.warning(
                "Ignoring an unreadable mention-analysis cache entry: %s", exc
            )
            return None
        if (
            entry.mention_id != snapshot.mention_id
            or entry.input_fingerprint != self._fingerprint(snapshot)
            or entry.analyzer_version != self.analyzer_version
            or entry.prompt_bundle_version != self.prompt_bundle_version
            or entry.requested_model != self.requested_model
            or entry.analysis.mention_id != snapshot.mention_id
        ):
            return None
        return entry.analysis

    def put(self, snapshot: MentionSnapshot, analysis: MentionAnalysis) -> None:
        if analysis.mention_id != snapshot.mention_id:
            raise ValueError("Cannot cache analysis for a different mention ID")
        entry = MentionCacheEntry(
            mention_id=snapshot.mention_id,
            input_fingerprint=self._fingerprint(snapshot),
            analyzer_version=self.analyzer_version,
            prompt_bundle_version=self.prompt_bundle_version,
            requested_model=self.requested_model,
            analysis=analysis,
            cached_at=datetime.now(timezone.utc),
        )
        self.store.write_json(self._path(snapshot.mention_id), entry)

    def _path(self, mention_id: uuid.UUID) -> Path:
        value = str(mention_id)
        return (
            self.store.root
            / "cache"
            / "mention-analysis"
            / self.namespace
            / value[:2]
            / f"{value}.json"
        )

    @staticmethod
    def _fingerprint(snapshot: MentionSnapshot) -> str:
        payload = json.dumps(
            snapshot.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
