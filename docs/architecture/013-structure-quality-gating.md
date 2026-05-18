# ADR 013 — Structure Quality Gating & Failure Isolation v1

## Status

Accepted (2026-05-18)

## Context

ADR 009's `paper ingest-full` chains DeepSeek structuring → `validate_question()`
→ `save_processing_result()` as a single block. If any question in the batch
fails validation, there is no per-question gating — the entire save step either
succeeds or the pipeline halts at a critical step.

ADR 012 improved question count accuracy, but **structural quality** of
individual DeepSeek outputs is still unmeasured at the batch level. We need:

- Per-question quality gating that decides whether a question is safe to save
- Failure isolation: one bad question must not block the other 21
- Quality statistics visible in the run report for both dry-run and non-dry-run

## Decision

Add `gate_question()` to `quality.py` and integrate it into the orchestrator's
`_step_deepseek_structure()`.

### Gating rules

| Condition | Gate |
|-----------|------|
| `stem_latex` is empty (after strip) | `failed` |
| Single-choice with < 2 choices | `warning` |
| Single-choice answer not in choice labels | `warning` |
| Proof/short-answer with no `analysis_latex` | `warning` |
| Unbalanced `$` delimiters in stem/answer/analysis | `warning` |
| QuestionBlock has assets but stem+answer+analysis has no image reference | `warning` |
| None of the above | `pass` |

### Failure isolation

- `failed` questions are **not** written to `questions` or `question_blocks`
- Downstream steps that create question-scoped artifacts (asset links and
  current-paper duplicate fingerprints) use the same gated question/block set,
  so they do not reference dropped question blocks
- `warning` questions are written normally; the gating warning codes are
  recorded in the run report
- A single `failed` question does **not** fail the entire paper — the
  pipeline continues with remaining questions

### Run report additions

`run-report.json` gains five new fields:

```json
{
  "questions_passed": 20,
  "questions_warning": 2,
  "questions_failed": 0,
  "failed_question_ids": [],
  "quality_warning_counts": {
    "too_few_choices": 1,
    "unbalanced_latex_delimiters": 1
  }
}
```

### When all questions fail

If every question is gated as `failed`, the paper status is set to `partial`
rather than `completed` — the pipeline itself ran correctly, but no usable
questions were produced.

### Dry-run

Quality gating runs identically in dry-run mode. The run report includes the
same five fields. The only difference is that `save_questions` is skipped
(ADR 009 behavior, unchanged).

## Consequences

### Positive

- One malformed DeepSeek output can no longer block an entire paper
- Quality statistics are visible in both dry-run and non-dry-run modes
- Warning codes are aggregated for batch evaluation tools
- Existing `validate_question()` is unchanged; gating is additive

### Negative

- `gate_question()` duplicates some checks from `validate_question()` with
  different thresholds (e.g. "too few choices" uses < 2 for gating vs < 4
  for quality reporting)
- Failed questions and their blocks are silently dropped from DB; the only
  record is in the run report

### Risk mitigation

- `failed_question_ids` in the run report makes every dropped question
  auditable
- Warning codes are aggregated with counts for trend analysis
- All existing tests must pass unchanged
