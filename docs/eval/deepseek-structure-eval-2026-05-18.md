# DeepSeek Structure Quality Evaluation — 2026-05-18

## Summary

| Metric | Value |
|--------|-------|
| Total PDFs | 3 |
| Pipeline completed | 3 |
| Pipeline partial | 0 |
| Pipeline failed | 0 |
| Total structured questions | 63 |
| Questions passed | 35 |
| Questions warning | 28 |
| Questions failed | 0 |
| Pass rate | 55.6% |
| Warning rate | 44.4% |
| Total elapsed | 988s |
| Avg per PDF | 329.5s |

## Per-Paper Results

| Paper ID | Layout Q | Structured | Passed | Warning | Failed | Status | Elapsed |
|----------|----------|------------|--------|---------|--------|--------|---------|
| deepseek_eval_0001 | 21 | 21 | 11 | 10 | 0 | completed | 61.2s |
| deepseek_eval_0002 | 21 | 21 | 14 | 7 | 0 | completed | 618.2s |
| deepseek_eval_0003 | 21 | 21 | 10 | 11 | 0 | completed | 309.1s |

## Quality Warning Distribution

| Warning Code | Count |
|--------------|-------|
| missing_analysis | 14 |
| answer_not_in_choices | 10 |
| asset_without_text_reference | 4 |
| too_few_choices | 3 |

## Per-Paper Detail

### deepseek_eval_0001

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 11
- Warning: 10
- Failed: 0
- Warning counts: {"too_few_choices": 1, "answer_not_in_choices": 4, "missing_analysis": 5, "asset_without_text_reference": 1}
- Elapsed: 61.2s
- Run report: `data/runs/deepseek_eval/deepseek_eval_0001/run-report.json`

### deepseek_eval_0002

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 14
- Warning: 7
- Failed: 0
- Warning counts: {"too_few_choices": 1, "answer_not_in_choices": 1, "missing_analysis": 5, "asset_without_text_reference": 1}
- Elapsed: 618.2s
- Run report: `data/runs/deepseek_eval/deepseek_eval_0002/run-report.json`

### deepseek_eval_0003

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 10
- Warning: 11
- Failed: 0
- Warning counts: {"answer_not_in_choices": 5, "too_few_choices": 1, "asset_without_text_reference": 2, "missing_analysis": 4}
- Elapsed: 309.1s
- Run report: `data/runs/deepseek_eval/deepseek_eval_0003/run-report.json`

## Conclusion

**CONDITIONAL** — No questions failed gating, but 28 of 63 questions have warnings (44.4% > 30%).

Recommended actions before full-batch ingestion:
- Review the top warning codes above
- If `answer_not_in_choices` is dominant, check DeepSeek answer format vs choice label matching
- If `missing_analysis` is dominant, check whether answer section parsing covers all questions
