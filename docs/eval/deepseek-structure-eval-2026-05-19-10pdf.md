# DeepSeek Structure Quality Evaluation — 2026-05-19

## Summary

| Metric | Value |
|--------|-------|
| Total PDFs | 10 |
| Pipeline completed | 9 |
| Pipeline partial | 0 |
| Pipeline failed | 1 |
| Total structured questions | 213 |
| Questions passed | 200 |
| Questions warning | 11 |
| Questions failed | 2 |
| Pass rate | 93.9% |
| Warning rate | 5.2% |
| Total elapsed | 648s |
| Avg per PDF | 64.8s |

## Per-Paper Results

| Paper ID | Layout Q | Structured | Passed | Warning | Failed | Status | Elapsed |
|----------|----------|------------|--------|---------|--------|--------|---------|
| deepseek_eval_hardened10_0001 | 21 | 21 | 21 | 0 | 0 | completed | 50.2s |
| deepseek_eval_hardened10_0002 | 21 | 21 | 20 | 1 | 0 | completed | 45.9s |
| deepseek_eval_hardened10_0003 | 21 | 21 | 20 | 1 | 0 | completed | 55.6s |
| deepseek_eval_hardened10_0004 | 21 | 21 | 21 | 0 | 0 | completed | 57.3s |
| deepseek_eval_hardened10_0005 | 17 | 0 | 0 | 0 | 0 | failed | 23.5s |
| deepseek_eval_hardened10_0006 | 18 | 18 | 18 | 0 | 0 | completed | 67.7s |
| deepseek_eval_hardened10_0007 | 20 | 20 | 16 | 4 | 0 | completed | 52.7s |
| deepseek_eval_hardened10_0008 | 41 | 41 | 35 | 4 | 2 | completed | 143.0s |
| deepseek_eval_hardened10_0009 | 25 | 25 | 24 | 1 | 0 | completed | 58.9s |
| deepseek_eval_hardened10_0010 | 25 | 25 | 25 | 0 | 0 | completed | 92.8s |

## Quality Warning Distribution

| Warning Code | Count |
|--------------|-------|
| answer_not_in_choices | 6 |
| too_few_choices | 5 |
| empty_stem | 2 |

## Failed Questions

| Paper ID | Question ID |
|----------|-------------|
| deepseek_eval_hardened10_0008 | deepseek_eval_hardened10_0008_q_0021 |
| deepseek_eval_hardened10_0008 | deepseek_eval_hardened10_0008_q_0031 |

## Top Failure Reasons

| Reason | Count |
|--------|-------|
| DeepSeek: API error | 1 |
| Pipeline step failure | 1 |

## Per-Paper Detail

### deepseek_eval_hardened10_0001

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 21
- Warning: 0
- Failed: 0
- Elapsed: 50.2s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0001/run-report.json`

### deepseek_eval_hardened10_0002

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 20
- Warning: 1
- Failed: 0
- Warning counts: {"too_few_choices": 1}
- Elapsed: 45.9s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0002/run-report.json`

### deepseek_eval_hardened10_0003

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 20
- Warning: 1
- Failed: 0
- Warning counts: {"answer_not_in_choices": 1}
- Elapsed: 55.6s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0003/run-report.json`

### deepseek_eval_hardened10_0004

- Status: completed
- Layout questions: 21
- DeepSeek structured: 21
- Passed: 21
- Warning: 0
- Failed: 0
- Elapsed: 57.3s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0004/run-report.json`

### deepseek_eval_hardened10_0005

**Crash**: [deepseek_structure] DeepSeek response must be a JSON object.

### deepseek_eval_hardened10_0006

- Status: completed
- Layout questions: 18
- DeepSeek structured: 18
- Passed: 18
- Warning: 0
- Failed: 0
- Elapsed: 67.7s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0006/run-report.json`

### deepseek_eval_hardened10_0007

- Status: completed
- Layout questions: 20
- DeepSeek structured: 20
- Passed: 16
- Warning: 4
- Failed: 0
- Warning counts: {"answer_not_in_choices": 2, "too_few_choices": 2}
- Elapsed: 52.7s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0007/run-report.json`

### deepseek_eval_hardened10_0008

- Status: completed
- Layout questions: 41
- DeepSeek structured: 41
- Passed: 35
- Warning: 4
- Failed: 2
- Failed IDs: deepseek_eval_hardened10_0008_q_0021, deepseek_eval_hardened10_0008_q_0031
- Warning counts: {"answer_not_in_choices": 2, "too_few_choices": 2, "empty_stem": 2}
- Elapsed: 143.0s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0008/run-report.json`

### deepseek_eval_hardened10_0009

- Status: completed
- Layout questions: 25
- DeepSeek structured: 25
- Passed: 24
- Warning: 1
- Failed: 0
- Warning counts: {"answer_not_in_choices": 1}
- Elapsed: 58.9s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0009/run-report.json`

### deepseek_eval_hardened10_0010

- Status: completed
- Layout questions: 25
- DeepSeek structured: 25
- Passed: 25
- Warning: 0
- Failed: 0
- Elapsed: 92.8s
- Run report: `data/runs/deepseek_eval_hardened10/deepseek_eval_hardened10_0010/run-report.json`

## Conclusion

**BLOCKED** — One or more questions failed quality gating, or one or more PDF pipelines failed.

Must investigate before proceeding:
- Review failed question IDs in the report above
- Check DeepSeek response payloads for missing required fields
- Verify that `stem_latex` is never empty in DeepSeek output

## Baseline Comparison

| Evaluation | PDFs | Questions | Passed | Warning | Failed | Warning Rate | Verdict |
|------------|------|-----------|--------|---------|--------|--------------|---------|
| ADR 014 baseline | 3 | 63 | 35 | 28 | 0 | 44.4% | CONDITIONAL |
| ADR 015 hardened | 3 | 63 | 62 | 1 | 0 | 1.6% | PASS |
| ADR 016 hardened10 | 10 | 213 | 200 | 11 | 2 | 5.2% | BLOCKED |

## Diagnosis

- Quality warning rate is acceptable at 5.2%, below the 10% PASS target.
- The BLOCKED verdict is caused by hard failures, not broad quality degradation.
- `deepseek_eval_hardened10_0005` failed during `deepseek_structure` because one DeepSeek response was not a JSON object. This needs single-question retry/fallback instead of failing the whole paper.
- `deepseek_eval_hardened10_0008_q_0021` and `deepseek_eval_hardened10_0008_q_0031` are instruction-like numbered blocks, not real questions:
  - `1．每小题选出答案后...`
  - `1．用黑色墨水的钢笔或签字笔将答案写在答题卡上...`
- These two false question blocks indicate ADR 012 instruction filtering only covers pre-first-section preamble; it does not yet catch instruction blocks that appear before later paper parts/sections.

## Recommendation

Do not proceed to 100-PDF DeepSeek evaluation yet.

Next step should be ADR 017:

1. Add per-question DeepSeek retry/fallback so a malformed response affects only one question, not the whole paper.
2. Extend instruction-number filtering to later section/paper-part boundaries without weakening real after-section question detection.
3. Re-run the same 10-PDF batch and require:
   - pipeline_failed = 0
   - questions_failed = 0
   - warning rate <= 10%
