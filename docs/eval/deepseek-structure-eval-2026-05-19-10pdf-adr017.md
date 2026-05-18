# ADR 017 DeepSeek Structure Quality Re-Evaluation — 2026-05-19

This re-runs the same 10-PDF hardened DeepSeek batch after the ADR 017 fixes:
per-question DeepSeek retry/fallback and later-section instruction filtering.
The previous 10-PDF run was BLOCKED by 1 pipeline-level malformed JSON failure
and 2 empty-stem false question blocks; this run has 0 pipeline failures and
0 failed questions.

## Summary

| Metric | Value |
|--------|-------|
| Total PDFs | 10 |
| Pipeline completed | 10 |
| Pipeline partial | 0 |
| Pipeline failed | 0 |
| Total structured questions | 224 |
| Questions passed | 218 |
| Questions warning | 6 |
| Questions failed | 0 |
| Pass rate | 97.3% |
| Warning rate | 2.7% |
| Total elapsed | 684s |
| Avg per PDF | 68.4s |

## Per-Paper Results

| Paper ID | Layout Q | Structured | Passed | Warning | Failed | Status | Elapsed |
|----------|----------|------------|--------|---------|--------|--------|---------|
| deepseek_eval_hardened10_0001 | 21 | 21 | 21 | 0 | 0 | completed | 51.6s |
| deepseek_eval_hardened10_0002 | 21 | 21 | 20 | 1 | 0 | completed | 48.7s |
| deepseek_eval_hardened10_0003 | 21 | 21 | 21 | 0 | 0 | completed | 59.7s |
| deepseek_eval_hardened10_0004 | 21 | 21 | 21 | 0 | 0 | completed | 59.4s |
| deepseek_eval_hardened10_0005 | 17 | 17 | 16 | 1 | 0 | completed | 55.9s |
| deepseek_eval_hardened10_0006 | 18 | 18 | 18 | 0 | 0 | completed | 73.1s |
| deepseek_eval_hardened10_0007 | 18 | 18 | 16 | 2 | 0 | completed | 55.7s |
| deepseek_eval_hardened10_0008 | 37 | 37 | 35 | 2 | 0 | completed | 134.2s |
| deepseek_eval_hardened10_0009 | 25 | 25 | 25 | 0 | 0 | completed | 57.5s |
| deepseek_eval_hardened10_0010 | 25 | 25 | 25 | 0 | 0 | completed | 88.2s |

## Quality Warning Distribution

| Warning Code | Count |
|--------------|-------|
| answer_not_in_choices | 4 |
| too_few_choices | 1 |
| deepseek_fallback | 1 |

## Per-Paper Detail

### deepseek_eval_hardened10_0001

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 21
- Warning: 0
- Failed: 0
- Elapsed: 51.6s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0001/run-report.json`

### deepseek_eval_hardened10_0002

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 20
- Warning: 1
- Failed: 0
- Warning counts: {"too_few_choices": 1}
- Elapsed: 48.7s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0002/run-report.json`

### deepseek_eval_hardened10_0003

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 21
- Warning: 0
- Failed: 0
- Elapsed: 59.7s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0003/run-report.json`

### deepseek_eval_hardened10_0004

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 21
- Warning: 0
- Failed: 0
- Elapsed: 59.4s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0004/run-report.json`

### deepseek_eval_hardened10_0005

- Status: completed
- Layout questions: 17
- DeepSeek structured: 17
- Passed: 16
- Warning: 1
- Failed: 0
- Warning counts: {"deepseek_fallback": 1}
- Elapsed: 55.9s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0005/run-report.json`

### deepseek_eval_hardened10_0006

- Status: completed
- Layout questions: 18
- DeepSeek structured: 18
- Passed: 18
- Warning: 0
- Failed: 0
- Elapsed: 73.1s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0006/run-report.json`

### deepseek_eval_hardened10_0007

- Status: completed
- Layout questions: 18
- DeepSeek structured: 18
- Passed: 16
- Warning: 2
- Failed: 0
- Warning counts: {"answer_not_in_choices": 2}
- Elapsed: 55.7s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0007/run-report.json`

### deepseek_eval_hardened10_0008

- Status: completed
- Layout questions: 37
- DeepSeek structured: 37
- Passed: 35
- Warning: 2
- Failed: 0
- Warning counts: {"answer_not_in_choices": 2}
- Elapsed: 134.2s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0008/run-report.json`

### deepseek_eval_hardened10_0009

- Status: completed
- Layout questions: 25
- DeepSeek structured: 25
- Passed: 25
- Warning: 0
- Failed: 0
- Elapsed: 57.5s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0009/run-report.json`

### deepseek_eval_hardened10_0010

- Status: completed
- Layout questions: 25
- DeepSeek structured: 25
- Passed: 25
- Warning: 0
- Failed: 0
- Elapsed: 88.2s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0010/run-report.json`

## Conclusion

**PASS** — All 224 questions passed quality gating with 6 warnings (2.7% ≤ 30%). DeepSeek structure output is acceptable for full-batch ingestion.
