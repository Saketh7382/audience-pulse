# Architecture

## Service responsibility

Audience Pulse is an independent worker service. It never collects social data
and it does not own project configuration.

```text
Control Plane                Data Harvester                 Audience Pulse
-------------                --------------                 --------------
orchestrates runs      ->    persists assets/mentions  ->  freezes run input
creates analysis row         completes connector tasks      analyzes evidence
publishes analysis job                                      writes result files
consumes progress event  <-                                 publishes progress
```

Analysis starts only from completed collection runs whose connector tasks all
succeeded. Control Plane resolves the cumulative run set and the largest exact
completed subset as its baseline. Snapshot queries remain scoped through
`run_mentions`; cumulative and new-only inputs are both deduplicated by mention ID.

## Runtime components

- `app/contracts`: versioned job, event, snapshot, intermediate, and final schemas.
- `app/db`: lifecycle metadata and read-only harvested-data snapshot queries.
- `app/llm`: provider-neutral structured inference and the OpenRouter adapter.
- `app/storage`: atomic local file operations and per-run process locks.
- `app/pipeline`: resumable stages, deterministic aggregation, evidence validation,
  exact-baseline trend comparison, cumulative/new metrics, and final assembly.
- `app/messaging`: Redis Streams delivery, retry, reclaim, acknowledgement, events,
  and dead-letter behavior.
- `app/worker.py`: dependency composition for worker and direct execution modes.

## Model routing

All model slugs are configuration. The default routing is:

| Stage | Default OpenRouter model |
|---|---|
| Mention understanding | `google/gemini-3.5-flash-lite` |
| Themes and asset/talent response | `google/gemini-3.5-flash` |
| Narrative, signals, and trends | `google/gemini-3.5-flash` |
| Recommendations and Executive Pulse | `google/gemini-3.5-flash` |
| Counts, percentages, ranking, deltas | Python; no LLM |

`ANALYZER_FALLBACK_MODELS` accepts any comma-separated OpenRouter slugs. The
gateway tries the primary model and then the configured model chain. The actual
serving model and usage are recorded for every generation.

## Evidence boundary

Raw authors are not included in analyzer snapshots or LLM prompts. Higher-level
stages receive deterministic aggregates and a bounded, diverse set of structured
mentions. Every cited mention ID is checked against the immutable input set before
an output is persisted. An invented ID fails the stage and triggers retry.

## Alpha deployment boundary

The local storage backend assumes one worker or a storage root mounted and shared
by all workers. Redis provides at-least-once delivery, while file locks prevent two
processes on the same filesystem from running the same analysis concurrently.

The `LocalAnalysisStore` is the only filesystem implementation. Keep pipeline
code behind this boundary so an object-storage implementation can replace it
without changing analysis behavior.
