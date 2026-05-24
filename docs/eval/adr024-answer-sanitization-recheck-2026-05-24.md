# ADR 024 Answer Sanitization Recheck — 2026-05-24

## Scope

Rechecked the three production-pilot papers that contributed most of the
`answer_not_in_choices` warnings after ADR 024 single-choice answer
sanitization.

The run reused existing MinerU artifacts with `--resume`, so MinerU parsing was
skipped. This isolates the check to Layout Ownership, real DeepSeek structuring,
and the ADR 024 hardening path.

## Command Shape

```bash
PYTHONPATH=src:. .venv/bin/python -m question_bank.cli paper ingest-full \
  --paper-id adr024_recheck_0004 \
  --pdf data/beta/pdf/paper_0004.pdf \
  --work-dir data/runs/adr024_recheck_2026-05-24/adr024_recheck_0004 \
  --asset-dir data/assets \
  --dry-run --resume --use-real-deepseek
```

The same command shape was used for `paper_0007.pdf` and `paper_0008.pdf`.

## Results

| Paper | Questions | Old warning | New warning | New passed | New failed |
| --- | ---: | ---: | ---: | ---: | ---: |
| paper_0004 | 21 | 1 | 0 | 21 | 0 |
| paper_0007 | 18 | 2 | 0 | 18 | 0 |
| paper_0008 | 37 | 2 | 0 | 37 | 0 |

## Aggregate

| Metric | Before ADR 024 | After ADR 024 |
| --- | ---: | ---: |
| Papers rechecked | 3 | 3 |
| Questions | 76 | 76 |
| `answer_not_in_choices` | 5 | 0 |
| Questions passed | 71 | 76 |
| Questions warning | 5 | 0 |
| Questions failed | 0 | 0 |

## Verdict

PASS for the targeted warning class.

ADR 024 eliminated the observed `answer_not_in_choices` warnings on the three
known affected papers without introducing failed questions. Because this was a
dry-run replay, asset persistence and crop/pHash behavior were intentionally not
re-evaluated.
