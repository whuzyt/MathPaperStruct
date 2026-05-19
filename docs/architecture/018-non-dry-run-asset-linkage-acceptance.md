# ADR 018: Non-Dry-Run Asset Linkage Acceptance

## Status

Accepted — 2026-05-19

## Context

Earlier PDF ingestion evaluations used `--dry-run`, which validates MinerU,
Layout Ownership, and DeepSeek structure quality but skips the database-backed
asset path:

1. `identify_assets`
2. `crop_assets`
3. `store_assets`
4. `compute_phash`
5. `visual_candidates`

The project needs evidence that real image/table/chart elements become
database rows, cropped files, pHash values, and question links.

## Decision

Run a non-dry-run acceptance batch against PostgreSQL using existing MinerU
artifacts and fresh paper IDs.

The batch may reuse MinerU output with `--resume` to avoid expensive VLM
parsing, but it must not reuse existing `raw_assets` rows. A fresh paper prefix
is required so `identify_assets` performs real inserts.

## Acceptance Gates

- `completed + partial >= 80%`
- at least one PDF has `question_asset_links > 0`
- crop success rate `>= 80%`
- pHash success rate `>= 80%`
- `raw_assets` with no `question_asset_links` equals `0` for the acceptance set
- `question_asset_links` must point to existing `question_blocks`
- no `data/runs`, `data/assets`, PDFs, or database files are committed

## Result

Report: `docs/eval/asset-linkage-eval-2026-05-19.md`

- PDFs: 5
- Completed: 5
- raw_assets: 16
- question_asset_links: 16
- crop successes: 16
- pHash computed: 16
- unlinked raw_assets: 0
- links without question_block: 0

Verdict: PASS.

