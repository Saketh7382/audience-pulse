# File contracts

## Run directory

Every analysis attempt gets an independent immutable directory:

```text
{storage_root}/projects/{project_id}/collection-runs/{collection_run_id}/analyses/{analysis_run_id}/
├── manifest.json
├── input/
│   ├── project_snapshot.json
│   ├── collection_summary.json
│   ├── mentions.jsonl
│   └── checksums.json
├── stages/
│   ├── 01_mention_analysis/batches/batch-000001.jsonl
│   ├── 02_aggregation/result.json
│   ├── 03_themes/result.json
│   ├── 04_asset_talent/result.json
│   ├── 05_narratives_signals/result.json
│   ├── 06_trends/result.json
│   └── 07_synthesis/result.json
└── final/
    ├── audience_pulse.json
    ├── executive_pulse.md
    ├── evidence.jsonl
    └── model_usage.json
```

The database stores paths relative to `ANALYZER_STORAGE_ROOT`. It never stores an
environment-specific absolute path.

## `manifest.json`

The manifest is the recovery journal. It contains run identity, schema/analyzer/
prompt versions, total and processed mention counts, stage states, output paths,
actual model usage, timestamps, and terminal errors.

It is rewritten atomically after each durable batch or stage. A stage is complete
only when its output has already been atomically renamed into place.

## Input files

`project_snapshot.json` contains descriptive campaign metadata, configured asset
identity, enabled connector identity, and active source identity. Connector
settings are deliberately excluded because they can contain API credentials.

`collection_summary.json` freezes the collection boundary and counts by platform
and collection tier.

`mentions.jsonl` has one object per `run_mentions` row:

```json
{
  "mention_id": "uuid",
  "asset_id": "uuid",
  "platform": "youtube_public",
  "record_type": "comment",
  "text": "BGM peaks ra kani VFX konchem rod la undi 😂",
  "published_at": "2026-09-28T00:00:00Z",
  "metrics": {"like_count": 24},
  "collection_tier": "target_assets",
  "asset_type": "trailer",
  "asset_title": "Official Trailer",
  "asset_url": "https://youtube.com/watch?v=example",
  "source_name": "Official channel"
}
```

`checksums.json` protects all three input files. A resumed, incomplete analysis
fails if the supposedly immutable snapshot changed.

## Mention-analysis JSONL

Every input mention must produce exactly one output. Duplicate, missing, or
unknown IDs fail the whole batch before it is saved.

The structured record contains language, optional normalized English meaning,
sentiment and strength, emotions, controlled film aspects, positive/negative
points, audience intent, questions, comparisons, expectations, speculation,
entities, and model confidence.

Original text is analyzed directly. `normalized_meaning_en` is supplementary and
never replaces the source text.

## Final files

`audience_pulse.json` is the canonical machine-readable output. It assembles
deterministic aggregation, themes, asset/talent response, narrative, strengths,
concerns, opportunities, risks, emerging signals, information gaps, trends,
recommendations, and Executive Pulse.

`executive_pulse.md` is a compact human-readable view for the business team.

`evidence.jsonl` maps every material finding to representative source mentions,
platforms, and assets without including author identity.

`model_usage.json` records stage, actual routed model, generation ID, input/output
tokens, optional OpenRouter cost, and generation time.

## Write guarantees

Files are written to a unique temporary sibling, flushed and fsynced, then moved
with `os.replace`. Completed batch files are never rewritten. If a worker crashes
after a batch rename but before a manifest update, resume validates and reuses the
batch rather than paying for it again.
