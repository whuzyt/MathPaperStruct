# ADR 021: Ingestion Reliability & Resume Hardening

## Status

Accepted — 2026-05-20

## Context

ADR 020 ran 20 PDFs through real ingestion. Results were strong (100% completion,
5.3% warning rate, 0 failed) but exposed reliability gaps:

1. **paper_0012** failed on its first run with a MinerU local API connection
   error — a transient failure that self-resolved on re-run. The pipeline
   treats all MinerU failures as fatal to the paper.

2. **Resume artifact checks** only check for file existence, not validity.
   A corrupted markdown or unparseable JSON would silently skip MinerU and
   fail downstream with cryptic errors.

3. **Re-running a single failed paper** requires either re-running the full
   20-PDF batch or hand-editing the tool invocation.

4. **Recomputing eval reports** after a re-run requires tedious manual work
   — there is no way to regenerate the markdown/JSON summary from existing
   run-report.json files.

## Decision

Implement four reliability hardenings:

### 1. MinerU Automatic Retry

Add retry logic to `LocalMinerURunner.parse_pdf()`:

- Maximum 2 retries (3 total attempts)
- Exponential backoff: 30s, 90s
- Only retry on **transient** errors matching known patterns:
  - Connection failures (refused, reset, aborted)
  - Timeout (connect, read)
  - DNS failures
  - Broken pipe / network unreachable
- Never retry on **non-transient** errors:
  - File not found / cannot open
  - Model missing / model download failure
  - Invalid CLI arguments
  - Permission denied

Pattern matching is case-insensitive substring match on the error message.

### 2. Resume Artifact Validity

Before skipping MinerU on resume, validate all three:

| Check | Failure mode |
|-------|-------------|
| Markdown file non-empty | Zero-byte or whitespace-only md |
| JSON file parseable | Truncated JSON from interrupted MinerU |
| JSON produces ≥ 1 layout element | Empty JSON arrays from MinerU model error |

If any check fails, clear the cached result and re-run MinerU.

### 3. Single-Paper Re-run

Add two flags to `tools/eval_real_e2e_beta.py`:

- `--only-index N`: Process only the Nth PDF (1-indexed)
- `--only-paper <substring>`: Process only PDFs matching the substring

### 4. Summarize-Existing Mode

Add `--summarize-existing` flag to `tools/eval_real_e2e_beta.py`:

- Reads `run-report.json` from each `work_root/<paper_id>/` directory
- Queries the database for asset link integrity (requires DB)
- Re-generates markdown and JSON summary reports
- Does NOT re-run any ingestion
- Fails clearly if DB is unavailable

### 5. Retry Tracking

When a paper is re-run (a previous `run-report.json` exists):

- The previous report is preserved as `run-report.previous.json`
- The eval result dict includes `retry_count` and `previous_error` fields
- The markdown report includes a "Retry History" section
- The per-paper table includes an "Rtry" column when any paper has retries

## Files Changed

| File | Change |
|------|--------|
| `src/question_bank/services/mineru.py` | Add `max_retries`, `retry_backoff_base`, transient error classification, retry loop, artifact discovery extract |
| `src/question_bank/services/paper_orchestrator.py` | Add `_validate_resume_artifacts()` with 3 checks |
| `tools/eval_real_e2e_beta.py` | Add `--summarize-existing`, `--only-index`, `--only-paper`, retry tracking, `_summarize_from_existing()`, `_main_summarize_existing()`, `_output_reports()` |

## Constraints

- Do NOT change Layout Ownership, DeepSeek prompt, or quality gating rules
- Do NOT commit data/runs, data/assets, PDFs, or DB files
- Retry is only for MinerU — DeepSeek retry is already handled by ADR 017

## Verification

1. `PYTHONPATH=src:tools python3 -m unittest discover -s tests -v` — all tests pass
2. Unit tests for transient vs non-transient error classification
3. Unit tests for resume artifact validity (empty md, bad json, no elements)
4. Unit tests for `--summarize-existing` (reads reports, queries DB)
5. Unit tests for `--only-index` (filters to single PDF)
6. Unit tests for retry tracking (previous_error preserved, Rtry column)
