# Muvion Audience Pulse

`audience-pulse` is the analysis boundary between harvested audience conversation
and Muvion's Release Pulse intelligence. It reads one completed collection run,
freezes the exact project/assets/mentions used for analysis, and progressively
produces evidence-backed structured files.

The service deliberately separates three responsibilities:

- PostgreSQL stores analysis lifecycle metadata and relative file paths only.
- Local files store immutable inputs, intermediate batches, and final outputs.
- OpenRouter supplies model-independent structured LLM inference.

## Alpha pipeline

```text
run_mentions snapshot
  -> mention understanding (LLM, immutable batches)
  -> deterministic aggregation (Python)
  -> themes (LLM)
  -> asset and talent response (LLM)
  -> narratives and signals (LLM)
  -> trends against the previous completed analysis (Python + LLM)
  -> recommendations and executive pulse (LLM)
  -> final JSON, Markdown, evidence JSONL, and usage JSON
```

Original audience text is analyzed directly. Indian-language, transliterated,
slang, emoji, and code-mixed text is never translated before classification.
The optional English normalized meaning is generated alongside—not instead of—
the original.

## Storage boundary

By default, run files live below `.analyzer-data/`, which is intentionally ignored
by Git. The database records paths relative to `ANALYZER_STORAGE_ROOT`, keeping
metadata portable between machines.

Local storage is an alpha deployment choice. Run a single worker, or place
`ANALYZER_STORAGE_ROOT` on a shared mounted volume before adding workers on
different machines.

## Setup

Python 3.11 or later is required.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
alembic upgrade head
python -m app --worker
```

For a direct local execution without Redis:

```bash
python -m app --run-id COLLECTION_RUN_UUID
```

The local command creates an analysis run, freezes its input, and executes the
same resumable pipeline used by the Redis worker.

## OpenRouter models

Every stage accepts an arbitrary OpenRouter model slug. Alpha defaults are:

- mention understanding: `google/gemini-3.5-flash-lite`
- themes, narrative and synthesis: `google/gemini-3.5-flash`
- optional fallback: `openai/gpt-5-mini`

No business logic imports a provider-specific SDK. Model routing is configuration,
so a later admin-facing policy can select a different provider/model by stage.

