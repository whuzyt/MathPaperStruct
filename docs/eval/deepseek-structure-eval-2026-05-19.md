# DeepSeek Structure Quality Evaluation — 2026-05-19

## Summary

| Metric | Value |
|--------|-------|
| Total PDFs | 3 |
| Pipeline completed | 3 |
| Pipeline partial | 0 |
| Pipeline failed | 0 |
| Total structured questions | 63 |
| Questions passed | 62 |
| Questions warning | 1 |
| Questions failed | 0 |
| Pass rate | 98.4% |
| Warning rate | 1.6% |
| Total elapsed | 157s |
| Avg per PDF | 52.2s |

## Per-Paper Results

| Paper ID | Layout Q | Structured | Passed | Warning | Failed | Status | Elapsed |
|----------|----------|------------|--------|---------|--------|--------|---------|
| deepseek_eval_hardened_0001 | 21 | 21 | 21 | 0 | 0 | completed | 51.6s |
| deepseek_eval_hardened_0002 | 21 | 21 | 20 | 1 | 0 | completed | 47.2s |
| deepseek_eval_hardened_0003 | 21 | 21 | 21 | 0 | 0 | completed | 57.9s |

## Quality Warning Distribution

| Warning Code | Count |
|--------------|-------|
| too_few_choices | 1 |

## Per-Paper Detail

### deepseek_eval_hardened_0001

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 21
- Warning: 0
- Failed: 0
- Elapsed: 51.6s
- Run report: `data/runs/deepseek_eval_hardened/deepseek_eval_hardened_0001/run-report.json`

### deepseek_eval_hardened_0002

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 20
- Warning: 1
- Failed: 0
- Warning counts: {"too_few_choices": 1}
- Elapsed: 47.2s
- Run report: `data/runs/deepseek_eval_hardened/deepseek_eval_hardened_0002/run-report.json`

### deepseek_eval_hardened_0003

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 21
- Warning: 0
- Failed: 0
- Elapsed: 57.9s
- Run report: `data/runs/deepseek_eval_hardened/deepseek_eval_hardened_0003/run-report.json`

## Conclusion

**PASS** — All 63 questions passed quality gating with 1 warnings (1.6% ≤ 30%). DeepSeek structure output is acceptable for full-batch ingestion.
