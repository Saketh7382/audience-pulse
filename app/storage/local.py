import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from pydantic import BaseModel

from app.contracts.analysis import AnalysisManifest


@dataclass(frozen=True)
class RunPaths:
    root: Path

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def input(self) -> Path:
        return self.root / "input"

    @property
    def stages(self) -> Path:
        return self.root / "stages"

    @property
    def final(self) -> Path:
        return self.root / "final"

    @property
    def lock(self) -> Path:
        return self.root / ".run.lock"


class LocalAnalysisStore:
    """Crash-safe alpha storage using immutable files and atomic manifests."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def paths(
        self,
        *,
        project_id: uuid.UUID,
        collection_run_id: uuid.UUID,
        analysis_run_id: uuid.UUID,
    ) -> RunPaths:
        return RunPaths(
            self.root
            / "projects"
            / str(project_id)
            / "collection-runs"
            / str(collection_run_id)
            / "analyses"
            / str(analysis_run_id)
        )

    def initialize(self, paths: RunPaths) -> None:
        for directory in (paths.root, paths.input, paths.stages, paths.final):
            directory.mkdir(parents=True, exist_ok=True)

    def relative(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.root))

    def resolve_relative(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(
                "Analysis path escapes the configured storage root"
            ) from exc
        return candidate

    def write_json(self, path: Path, value: BaseModel | dict | list) -> None:
        payload = (
            value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        )
        self._atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2))

    def read_json(self, path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    def write_jsonl(
        self,
        path: Path,
        values: Iterable[BaseModel | dict],
    ) -> None:
        lines: list[str] = []
        for value in values:
            payload = (
                value.model_dump(mode="json") if isinstance(value, BaseModel) else value
            )
            lines.append(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        text = "\n".join(lines)
        if lines:
            text += "\n"
        self._atomic_write(path, text)

    def iter_jsonl(self, path: Path) -> Iterator[dict[str, Any]]:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)

    def write_text(self, path: Path, text: str) -> None:
        self._atomic_write(path, text)

    def load_manifest(self, paths: RunPaths) -> AnalysisManifest | None:
        if not paths.manifest.exists():
            return None
        return AnalysisManifest.model_validate(self.read_json(paths.manifest))

    def save_manifest(self, paths: RunPaths, manifest: AnalysisManifest) -> None:
        self.write_json(paths.manifest, manifest)

    @contextmanager
    def acquire_run_lock(self, paths: RunPaths) -> Iterator[None]:
        """Prevent two local workers from executing the same analysis run."""
        import fcntl

        paths.root.mkdir(parents=True, exist_ok=True)
        with paths.lock.open("a+", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError(
                    f"Analysis run is already active at {paths.root}"
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
