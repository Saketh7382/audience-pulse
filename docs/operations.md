# Operations

## Install

```bash
cd audience-pulse
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Set `DATABASE_URL`, `REDIS_URL`, and `OPENROUTER_API_KEY`. Keep `.env` outside Git.

## Create the metadata table

```bash
alembic upgrade head
```

This service uses `audience_pulse_alembic_version`, not the control-plane's
`alembic_version`, so their independent migration histories cannot overwrite one
another.

## Start the worker

```bash
python -m app --worker
```

Process one Redis batch for controlled testing:

```bash
python -m app --worker --once
```

## Queue a completed collection run

Before control-plane integration is enabled, the service can create metadata and
publish a production-shaped job itself:

```bash
python -m app --enqueue-run-id COLLECTION_RUN_UUID
```

Run immediately without Redis:

```bash
python -m app --run-id COLLECTION_RUN_UUID
```

Resume an existing failed/incomplete attempt explicitly:

```bash
python -m app \
  --run-id COLLECTION_RUN_UUID \
  --analysis-run-id ANALYSIS_RUN_UUID
```

## Test

```bash
pytest -q
```

Tests use fake LLM and Redis implementations. They do not spend OpenRouter credit.

## Logging

At `INFO`, application logs are human-readable lifecycle messages. Dependency
libraries are restricted to warnings and errors. Set `LOG_FORMAT=json` for
machine-readable runtime logs, or `LOG_LEVEL=DEBUG` for development detail.

## Backup and scaling

For alpha, back up both PostgreSQL and `ANALYZER_STORAGE_ROOT`; either side alone
is incomplete. Do not run workers on different hosts unless they share the same
mounted storage root. A future object-store backend removes that constraint.
