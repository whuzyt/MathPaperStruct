# ADR 011 — Non-dry-run Asset Linkage Evaluation v1

## Status

Accepted (2026-05-17)

## Context

ADR 010 proved the main pipeline (MinerU → Layout Ownership → DeepSeek
structuring) is stable across 10 real PDFs at 100% dry-run success.  However,
dry-run skips `identify_assets`, `crop_assets`, `store_assets`, and
`compute_phash` — the entire image/asset linkage flow.  The database write
path (question_blocks, questions, question_assets, raw_assets,
question_asset_links) has never been exercised against real MinerU output.

We need a small-scale non-dry-run evaluation to verify:

- `identify_paper_assets()` produces `raw_assets` rows and
  `question_asset_links` rows for real PDFs containing images/tables/charts.
- `crop_pdf_assets()` correctly crops images from PDF pages using bbox
  coordinates and stores them on disk.
- `store_crop_result()` creates local file paths and writes metadata.
- `compute_phash()` generates perceptual hashes for cropped images.
- The full 10-step pipeline completes without crashes, 0 critical failures,
  and manageable warning rates.

## Decision

We introduce `tools/eval_asset_linkage.py`, a batch evaluation tool that
runs `ingest_paper_full()` in **non-dry-run** mode against a real PostgreSQL
database.

### Design

- Paper IDs prefixed with `asset_eval_` to isolate evaluation runs from
  production data.
- DeepSeek remains `FakeDeepSeekClient` — the goal is structural
  correctness, not model accuracy.
- Each run queries the database after completion to extract supplementary
  metrics not recorded in the orchestrator report (e.g. link counts,
  unassigned assets, low-confidence assignments).
- The tool checks database connectivity and schema existence before
  processing any PDFs, failing with a clear error if tables are missing.
- Duplicate candidates and visual candidates are skipped (non-critical
  cross-paper steps irrelevant to single-paper asset evaluation).

### Database isolation

- Paper IDs use a configurable prefix (default `asset_eval_`).
- The tool never drops or truncates tables.
- Repeated runs with the same paper prefix and `--resume` will skip MinerU
  (when artifacts exist) and skip `identify_assets` (when raw_assets already
  exist for that paper), making re-runs idempotent.

### Report

Output: `docs/eval/asset-linkage-eval-YYYY-MM-DD.md`

Fields per paper:
- `paper_id`
- `layout question_count`
- `MinerU image/table/chart count` (from content_list.json element types)
- `raw_assets count` (from DB)
- `question_asset_links count` (from DB)
- `crop success count` / `crop failed count` (from orchestrator step)
- `phash success count` (from orchestrator step)
- `unassigned_visual_asset count` (raw_assets without a question link)
- `asset_assignment_conflict count` (TBD — v1 reports 0)
- `low_confidence_asset_assignment count` (links with confidence < 0.8)
- `run-report path`

## Consequences

### Positive

- Validates that assets survive the full write path: element → raw_asset →
  crop → store → phash → link.
- Identifies gaps in the asset identification/linkage logic before scaling
  to the full corpus.
- Provides a repeatable evaluation harness for future pipeline changes.

### Negative

- Requires a running PostgreSQL instance (local Docker Compose or
  development server).
- Non-dry-run runs produce real files in `data/assets/` and DB rows that
  must be managed.
- Asset evaluation runs are slower than dry-run due to I/O (crop images,
  write to DB).

### Risk mitigation

- Paper ID prefix prevents pollution of production data.
- Tool checks DB schema before processing; fails fast if tables missing.
- `--limit` and `--resume` flags allow incremental testing.
- Reports are timestamped and never overwritten.

## Alternatives considered

1. **Extend ADR 010 batch tool with a `--no-dry-run` flag.**  Rejected —
   the asset-specific metrics (link counts, unassigned assets,
   conflicts) require DB queries and MinerU element-type analysis that
   would bloat the general-purpose batch tool.

2. **Write a dedicated integration test suite instead of a CLI tool.**
   Rejected — tests can't run MinerU (sandbox restriction).  The eval
   tool is designed for real-terminal execution against real PDFs and a
   real DB.

3. **Run non-dry-run on the full 106-PDF corpus immediately.**
   Rejected — too risky without first validating the asset write path on
   a small sample.
