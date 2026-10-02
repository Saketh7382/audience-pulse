# Muvion Audience Pulse

`audience-pulse` is the independent analysis service between harvested audience
conversation and Muvion's Release Pulse intelligence. It freezes the cumulative
set of completed project runs plus a genuinely-new mention cohort, analyzes them
through small evidence-backed stages, and writes structured files for the
business/reporting layer.

## Responsibilities

- PostgreSQL stores analysis lifecycle metadata, versions, counts, usage, and
  relative file paths only.
- Local files store immutable inputs, completed mention batches, intermediate
  intelligence, final JSON, final Markdown, evidence, and model usage.
- OpenRouter supplies provider-neutral structured inference.
- Python calculates counts, percentages, rankings, and changes without an LLM.

## Alpha pipeline

```text
run_mentions snapshot
  -> mention understanding (LLM, immutable batches)
  -> cumulative + new-cohort deterministic aggregation (Python)
  -> themes (LLM)
  -> asset and talent response (LLM)
  -> narratives and signals (LLM)
  -> trends against the previous Pulse (Python + LLM)
  -> recommendations and Executive Pulse (LLM)
  -> final JSON, Markdown, evidence JSONL, and usage JSON
```

Original audience text is analyzed directly. Indian-language, transliterated,
slang, emoji, and code-mixed text is never translated before classification. An
optional normalized English meaning accompanies the original understanding.

## Models through OpenRouter

Every stage accepts an arbitrary OpenRouter model slug. Alpha defaults are:

- mention understanding: `google/gemini-3.5-flash-lite`
- themes, narratives, trends, and synthesis: `google/gemini-3.5-flash`
- cross-provider fallback: `openai/gpt-5-mini`

Configure any other model by changing the stage environment variables. Business
logic does not import a Google, OpenAI, or Anthropic SDK.

## Quick start

Python 3.11 or later is required.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
alembic upgrade head
python -m app --worker
```

Normally, Control Plane automatically resolves all completed project collection
runs and queues a cumulative analysis when collection completes. The same flow is
exposed as bodyless `POST /api/v1/projects/{project_id}/analysis`; callers never
select run IDs. The job still carries immutable run IDs internally for lineage.

If the prior Pulse covered runs 1–4 and run 5 is now complete, the next Pulse
covers runs 1–5 and names the 1–4 Pulse as its exact baseline. Mentions already
seen in runs 1–4 are excluded from the run-5 incremental cohort, even if run 5
re-associated them. Mention-level cache entries avoid repeating classification.
The explicit single-run CLI remains available only for recovery and testing:


```bash
python -m app --enqueue-run-id COLLECTION_RUN_UUID
```

Or run it directly without Redis:

```bash
python -m app --run-id COLLECTION_RUN_UUID
```

Resume a specific attempt:

```bash
python -m app --run-id COLLECTION_RUN_UUID --analysis-run-id ANALYSIS_RUN_UUID
```

Run tests without spending OpenRouter credit:

```bash
pytest -q
```

## Mention-analysis cost cache

The expensive per-mention structured result is cached below
`.analyzer-data/cache/mention-analysis/`. Cache entries are isolated by analyzer
version, prompt-bundle version, and requested model, and each entry includes a
fingerprint of only the fields sent to the mention-analysis prompt. Mutable
engagement counters, collection timestamps, and URLs do not invalidate an
otherwise identical analytical result.

A later analysis reuses matching mention results without an OpenRouter call and
runs the model only for new or changed mentions. Project-level themes, narrative,
asset/talent interpretation, and synthesis still run for every analysis so their
conclusions reflect the complete selected dataset. Cache hit and miss counts are
written to the manifest and final `audience_pulse.json`.

Changing `ANALYZER_VERSION`, `PROMPT_BUNDLE_VERSION`, or
`ANALYZER_MENTION_MODEL` creates a new cache namespace instead of silently
reusing results produced under a different analytical contract.

Worker retries are bounded. After the final failure, the worker writes the job to
the dead-letter stream, marks the corresponding `analysis_runs` row as `failed`,
and only then acknowledges the source message. The Control Plane retry endpoint
can requeue that exact immutable attempt.

## Storage

The default root is `.analyzer-data/`, ignored by Git. Database paths are relative
to `ANALYZER_STORAGE_ROOT`, making them portable. Local storage is an alpha
choice: use one worker, or a shared mounted volume before running workers across
multiple machines.

## Documentation

- [Architecture](docs/architecture.md)
- [File contracts](docs/file-contracts.md)
- [Redis contracts](docs/redis-contracts.md)
- [Operations](docs/operations.md)
