# Redis contracts

## Analysis jobs

- Stream: `audience:analysis:jobs`
- Consumer group: `audience-pulse-workers`
- Field: `payload`
- Payload: versioned `AnalysisJob` JSON

```json
{
  "schema_version": 1,
  "analysis_run_id": "d84282c5-71c3-4cf9-80eb-2a7cc97cc9b9",
  "collection_run_id": "5c7acdb7-10bc-4341-89ae-f7847ce4646b",
  "project_id": "191e459d-831a-4bed-a624-5144a98d16df",
  "enqueued_at": "2026-09-28T10:00:00Z"
}
```

The `analysis_runs` row must exist before publication and its project/collection
identity must match the job. The worker rejects mismatched jobs.

The worker acknowledges only after final files and completed database metadata
are durable. Failed work remains pending and is reclaimed after the configured
idle time. Exhausted or invalid jobs are acknowledged only after a copy is placed
on `audience:analysis:jobs:dead-letter`.

## Progress events

- Stream: `audience:analysis:events`
- Field: `payload`
- Payload: versioned `AnalysisProgressEvent` JSON

Events communicate lifecycle metadata only: status, stage, percentage, processed
and total mention counts, final paths, errors, and timestamps. Analytical content
does not travel through Redis.

Recommended control-plane behavior is to consume this stream with its own group,
guard terminal states, update `analysis_runs`, and forward presentation-safe
progress to clients over WebSockets.

## Delivery semantics

Redis Stream entries remain visible after acknowledgement by design. `XACK`
removes them from the pending list; `MAXLEN` bounds retained history. This service
does not call `XDEL` for normal jobs.
