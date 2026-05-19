# ADR 020: Small-Scale Real Ingestion Beta

## Status

Accepted — 2026-05-20

## Context

ADR 019 validated the combined path (real DeepSeek + PostgreSQL writes + asset
linkage) on 3 PDFs with 63 questions and passed all acceptance gates.  The next
step is a larger batch — 20 PDFs — to validate:

- Batch stability: no pipeline failures across 20 PDFs
- Quality gating at scale: warning rate stays low
- Asset pipeline robustness: crop, pHash across more images
- Duplicate/visual candidate group discovery at meaningful scale
- DB write throughput: concurrent paper writes without conflicts

## Decision

Run a 20-PDF real ingestion beta with the following parameters:

- 20 PDFs from `data/beta/pdf`
- Paper prefix: `real_beta_2026_05_19`
- Real DeepSeek API
- Non-dry-run PostgreSQL writes
- `--resume` to reuse existing MinerU artifacts (avoids VLM re-parsing)

## Acceptance Gates

| Gate | Threshold |
|------|-----------|
| `completed + partial >= 90%` | ≥ 18 of 20 |
| `pipeline failed = 0` | 0 |
| `questions_failed = 0` | 0 |
| Warning rate | ≤ 10% |
| `raw_assets > 0` on ≥ 50% PDFs | ≥ 10 of 20 |
| `question_asset_links > 0` | > 0 |
| Unlinked raw assets | ≤ 10% |
| Links without question block | 0 |
| Crop success rate | ≥ 80% |
| pHash success rate | ≥ 80% |

## Per-Paper Metrics

Each PDF reports:

- status, pages, layout_count, structured_count
- questions_passed / warning / failed
- quality_warning_counts
- raw_assets, question_asset_links
- crop_success, crop_failed
- phash_success
- duplicate_candidate_groups, visual_candidate_groups
- elapsed_s

## Outputs

- Markdown report: `docs/eval/real-e2e-beta-2026-05-20.md`
- JSON summary: `data/runs/real_beta_2026-05-19/real-e2e-beta-summary-2026-05-20.json`

## Result

The final beta run passed all acceptance gates:

- 20/20 PDFs completed, 0 pipeline failures
- 472 structured questions, 447 pass / 25 warning / 0 failed
- Warning rate: 5.3%
- 187 raw assets, 187 question-asset links
- 0 unlinked raw assets, 0 links without a question block
- 187/187 crop success, 187/187 pHash success

## Constraints

- Do NOT restructure `layout_ownership` or change the DeepSeek prompt
- Do NOT commit `data/runs`, `data/assets`, PDFs, or DB files
- Use `--resume` for MinerU (pre-run MinerU outside sandbox)
- This is a verification run, not a production ingestion
