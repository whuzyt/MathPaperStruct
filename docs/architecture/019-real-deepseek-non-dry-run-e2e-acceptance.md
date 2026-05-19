# ADR 019: Real DeepSeek Non-Dry-Run E2E Acceptance

## Status

Accepted — 2026-05-19

## Context

Previous gates validated the major subsystems separately:

- ADR 017: real DeepSeek structure quality passed in dry-run mode.
- ADR 018: non-dry-run asset linkage passed with the fake DeepSeek client.

The remaining risk was the combined path: real DeepSeek, PostgreSQL writes,
question saving, raw asset linkage, crop storage, pHash computation, duplicate
candidates, and visual candidates in the same ingestion run.

## Decision

Run a small real end-to-end acceptance batch:

- 3 PDFs from `data/beta/pdf`
- fresh paper prefix: `adr019_real_e2e`
- `--use-real-deepseek`
- non-dry-run PostgreSQL writes
- `--resume` using existing MinerU artifacts to avoid re-running VLM parsing

## Acceptance Gates

- `completed + partial >= 80%`
- `questions_failed = 0`
- quality warning rate `<= 10%`
- `raw_assets > 0`
- `question_asset_links > 0`
- crop success rate `>= 80%`
- pHash success rate `>= 80%`
- persisted `question_asset_links` point to existing `question_blocks`
- no `data/runs`, `data/assets`, PDFs, or database files are committed

## Result

Report: `docs/eval/real-e2e-acceptance-2026-05-19.md`

- PDFs: 3
- Completed: 3
- Structured questions: 63
- Questions passed: 61
- Questions warning: 2
- Questions failed: 0
- Warning rate: 3.2%
- raw_assets: 4
- question_asset_links: 4
- crop success: 4/4
- pHash success: 4/4
- unlinked raw_assets: 0
- links without question_block: 0

Verdict: PASS.

