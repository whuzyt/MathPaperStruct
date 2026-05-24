# ADR 022: Production Batch Runner & Observability

## Status

Accepted — 2026-05-20

## Context

ADR 021 hardened individual PDF ingestion with retry, resume validation, and
single-paper re-run. But running 100+ PDFs at production scale requires:

1. A **production-grade batch runner** that's non-dry-run by default, with
   PostgreSQL and DeepSeek as hard requirements (not optional).

2. **Manifest-driven recovery** — when a batch run of 100 PDFs crashes on PDF
   #73, re-running should skip the first 72 and resume from the failure point.

3. **Observability** beyond per-paper counts — step-level timing to identify
   bottlenecks (is MinerU or DeepSeek dominating wall clock?), throughput
   metrics (sec/page, sec/question), and a failure taxonomy to track error
   categories across runs.

4. Clear **semantic separation** between eval tools (dry-run-first, optional DB)
   and production tools (non-dry-run, DB-required).

## Decision

Create `tools/batch_real_ingest.py` as the single production batch runner with
six observability features:

### 1. Production Batch Runner (`tools/batch_real_ingest.py`)

Non-dry-run by default. Requires `DEEPSEEK_API_KEY` and PostgreSQL — fails
clearly with exit code 1 or 2 if either is missing.

Reuses `ingest_paper_full` from `paper_orchestrator.py` with `dry_run=False`.
Follows the `_process_one_pdf` / `_process_one_safe` pattern from
`tools/eval_real_e2e_beta.py` but produces a production-oriented result dict
rather than an eval report.

Arguments:

| Flag | Default | Description |
|------|---------|-------------|
| `--pdf-dir` | (required) | Directory of PDF files |
| `--work-root` | `data/runs/batch_<date>` | Per-paper work directories |
| `--asset-dir` | `data/assets` | Asset storage directory |
| `--paper-prefix` | derived from work-root | Prefix for paper IDs |
| `--limit` | None | Max PDFs to process |
| `--resume` | False | Resume from existing `batch-manifest.json` |
| `--only-index` | None | Process only the Nth PDF (1-indexed) |
| `--only-paper` | None | Process only PDFs matching substring |
| `--fail-fast` | False | Stop on first failure |
| `--report-dir` | `docs/eval` | Output directory for batch report |

### 2. Manifest-Driven Recovery

A `batch-manifest.json` file in `work_root` tracks per-PDF state:

```json
[
  {
    "paper_id": "batch_2026_05_20_0001",
    "pdf_path": "/path/to/paper.pdf",
    "status": "completed",
    "started_at": "2026-05-20T10:30:00+00:00",
    "finished_at": "2026-05-20T10:35:12+00:00",
    "attempts": 1,
    "last_error": null,
    "run_report_path": "data/runs/batch_2026-05-20/batch_2026_05_20_0001/run-report.json"
  }
]
```

Status transitions: `pending` → `running` → `completed` | `partial` | `failed` | `crashed`

Resume behavior (`--resume`):
- `completed`, `partial` → **skip** (work already done)
- `failed`, `crashed`, `pending`, `running` → **re-run**

Manifest is saved after every paper (not just at the end), so a crash loses
at most one paper's progress.

### 3. Step-Level Timing

`_extract_step_timings()` parses `started_at` and `finished_at` ISO timestamps
from each paper's `step_data` to compute per-step aggregates:

| Metric | Source |
|--------|--------|
| `total_s` | Sum of all step durations |
| `count` | Number of papers with this step |
| `avg_s` | Mean step duration |
| `max_s` | Slowest single run |
| `slowest_paper` | Paper ID of the max |
| `pct_of_wall` | Percentage of wall-clock time |

The `% Wall` column helps identify whether MinerU or DeepSeek dominates total
runtime.

### 4. Failure Taxonomy

`_classify_failure()` maps error text to one of 8 categories:

| Category | Match pattern |
|----------|--------------|
| `mineru_transient` | mineru + connection/timeout/refused/reset/broken pipe |
| `mineru_non_transient` | mineru but no transient pattern |
| `deepseek` | "deepseek" in error |
| `database` | database/psycopg/postgres in error |
| `layout` | "layout" in error |
| `asset_crop` | "crop" in error |
| `asset_store` | "store" or "storage" in error |
| `unknown` | No pattern matched |

Each category in the report includes a count and an example (first 100 chars of
a representative error).

### 5. Throughput Report

Computed from wall-clock time and aggregate counts:

| Metric | Formula |
|--------|---------|
| sec/PDF | `wall_elapsed / total_pdfs` |
| sec/page | `wall_elapsed / total_pages` |
| sec/question | `wall_elapsed / total_questions` |

### 6. Reports

Two output formats:

**Markdown report** (`docs/eval/batch-<date>.md`) with 8 sections:
1. Summary — completion counts, success rate, question totals
2. Throughput — sec/PDF, sec/page, sec/question
3. Asset Pipeline — raw_assets, QA links, crop success/fail, pHash
4. Step Timing — per-step avg/max/% wall
5. Failure Taxonomy — category counts with examples
6. Per-Paper Results — table with all metrics per paper
7. Quality Warning Distribution — aggregated warning codes
8. Errors — paper-level error details

**JSON summary** (`work_root/batch-summary-<date>.json`) with manifest,
results, questions, throughput, assets, step_timing, failure_taxonomy, and
per-paper arrays.

## Files Changed

| File | Change |
|------|--------|
| `tools/batch_real_ingest.py` | New — production batch runner with manifest, timing, taxonomy, throughput |
| `docs/architecture/022-production-batch-runner-observability.md` | New — this ADR |

## Constraints

- Do NOT change Layout Ownership, DeepSeek prompt, or quality gating rules
- Do NOT commit data/runs, data/assets, PDFs, or DB files
- **No concurrency** — serial processing only (v1 simplicity)
- Production and eval semantics remain separate (eval = dry-run-first, optional DB; production = non-dry-run, DB-required)
- Manifest is saved after every paper for crash resilience

## Verification

1. `PYTHONPATH=src:tools python3 -m unittest discover -s tests -v` — all tests pass
2. Unit tests for manifest init (fresh entries for PDF list)
3. Unit tests for resume behavior (skip completed/partial, rerun failed/crashed)
4. Unit tests for `--only-index` (filters to single PDF)
5. Unit tests for `--fail-fast` (stops on first failure)
6. Unit tests for step timing aggregation (correct avg, max, slowest_paper)
7. Unit tests for failure taxonomy classification (8 categories)
8. Unit tests for markdown report (throughput, timing, taxonomy sections present)
9. Unit tests for JSON summary (manifest and throughput fields present)
