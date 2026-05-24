# ADR 023: Production Batch Preflight Gate

## Status

Accepted — 2026-05-24

## Context

ADR 022 added a production batch runner for real non-dry-run ingestion. Before
processing 20/100 PDFs, the runner must fail fast on environment problems that
are not paper-specific:

1. Missing or invalid `DEEPSEEK_API_KEY`
2. Missing MinerU executable
3. PostgreSQL unavailable
4. Database schema not initialized
5. Output directories not writable

Without a preflight gate, those failures can appear only after manifest creation
or after the first PDF starts, making production runs harder to resume and
debug.

## Decision

Add a production preflight gate to `tools/batch_real_ingest.py`.

The gate runs before creating the DeepSeek client and before constructing the
repository. It checks:

| Check | Failure behavior |
|-------|------------------|
| `DEEPSEEK_API_KEY` configured and not obviously invalid | exit code 1, actionable message |
| `MINERU_COMMAND` resolvable as path or PATH command | exit code 2 |
| `work-root`, `asset-dir`, `report-dir` writable | exit code 2 |
| `psycopg` importable | exit code 2 |
| PostgreSQL connection succeeds | exit code 2 |
| `SELECT 1` succeeds | exit code 2 |
| Required DB tables exist | exit code 2 with `db init` instruction |

Required tables:

- `papers`
- `question_blocks`
- `questions`
- `choices`
- `quality_reports`
- `raw_assets`
- `question_asset_links`
- `duplicate_candidate_groups`
- `canonical_questions`
- `canonical_assets`

The gate does not call DeepSeek or MinerU. It only verifies local configuration,
filesystem writability, and database readiness. `batch-manifest.json` is not
written until the preflight passes, so setup failures do not create misleading
batch state.

## Consequences

Production batch failures become easier to classify:

- Preflight failure: environment/config/schema issue; no PDF has started.
- Paper failure: per-PDF ingestion failure captured by manifest and reports.

This keeps ADR 022 manifest semantics clean and avoids polluting batch results
with global setup errors.

## Verification

Unit tests cover:

1. MinerU command path validation
2. Missing MinerU command error
3. DeepSeek key placeholder and prefix validation
4. Writable directory creation and probe
5. Successful PostgreSQL connection/schema check
6. PostgreSQL connection failure
7. Missing schema table failure
