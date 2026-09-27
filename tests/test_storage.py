import uuid
from datetime import datetime, timezone

from app.contracts.analysis import AnalysisManifest, MentionSnapshot
from app.storage.local import LocalAnalysisStore


def test_local_store_round_trips_manifest_and_jsonl(tmp_path):
    store = LocalAnalysisStore(tmp_path)
    project_id = uuid.uuid4()
    collection_run_id = uuid.uuid4()
    analysis_run_id = uuid.uuid4()
    paths = store.paths(
        project_id=project_id,
        collection_run_id=collection_run_id,
        analysis_run_id=analysis_run_id,
    )
    store.initialize(paths)
    manifest = AnalysisManifest(
        analysis_run_id=analysis_run_id,
        collection_run_id=collection_run_id,
        project_id=project_id,
        analyzer_version="test",
        prompt_bundle_version="test",
    )
    store.save_manifest(paths, manifest)

    mention = MentionSnapshot(
        mention_id=uuid.uuid4(),
        asset_id=uuid.uuid4(),
        platform="youtube_public",
        record_type="comment",
        text="BGM peaks ra kani VFX konchem rod la undi 😂",
        published_at=datetime.now(timezone.utc),
        collection_tier="target_assets",
        asset_type="trailer",
        asset_url="https://youtube.com/watch?v=test",
    )
    mentions_path = paths.input / "mentions.jsonl"
    store.write_jsonl(mentions_path, [mention])

    assert store.load_manifest(paths) == manifest
    restored = list(store.iter_jsonl(mentions_path))
    assert restored[0]["text"] == mention.text
    assert store.relative(paths.manifest).endswith("manifest.json")


def test_run_lock_rejects_concurrent_owner(tmp_path):
    store = LocalAnalysisStore(tmp_path)
    paths = store.paths(
        project_id=uuid.uuid4(),
        collection_run_id=uuid.uuid4(),
        analysis_run_id=uuid.uuid4(),
    )
    store.initialize(paths)

    with store.acquire_run_lock(paths):
        try:
            with store.acquire_run_lock(paths):
                raise AssertionError("second lock should not be acquired")
        except RuntimeError as exc:
            assert "already active" in str(exc)


def test_relative_path_resolution_cannot_escape_storage_root(tmp_path):
    store = LocalAnalysisStore(tmp_path)

    try:
        store.resolve_relative("../outside.json")
        raise AssertionError("path traversal should fail")
    except ValueError as exc:
        assert "escapes" in str(exc)
