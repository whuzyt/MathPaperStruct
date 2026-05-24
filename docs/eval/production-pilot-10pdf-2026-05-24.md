# Production Pilot 10-PDF Batch — 2026-05-24

## Summary

| Metric | Value |
|--------|-------|
| Tool | `tools/batch_real_ingest.py` |
| Mode | non-dry-run |
| PDFs | 10 |
| Pages | 119 |
| Completed | 10 |
| Partial | 0 |
| Failed | 0 |
| Crashed | 0 |
| Success rate | 100.0% |
| Wall clock | 3661.7s |

## Question Quality

| Metric | Value |
|--------|-------|
| Layout questions | 224 |
| Structured questions | 224 |
| Questions passed | 215 |
| Questions warning | 9 |
| Questions failed | 0 |
| Warning rate | 4.0% |

Warning distribution:

| Warning Code | Count |
|--------------|-------|
| `answer_not_in_choices` | 7 |
| `too_few_choices` | 1 |
| `deepseek_fallback` | 1 |

## Asset Pipeline

| Metric | Value |
|--------|-------|
| Raw assets | 79 |
| Question-asset links | 79 |
| Crop success | 79 |
| Crop failed | 0 |
| Crop success rate | 100.0% |
| pHash computed | 79 |

## Throughput

| Metric | Value |
|--------|-------|
| sec/PDF | 366.2s |
| sec/page | 30.8s |
| sec/question | 16.3s |

## Step Timing

| Step | Total | Avg | Max | Share | Slowest |
|------|-------|-----|-----|-------|---------|
| MinerU parse | 3068.8s | 306.9s | 611.4s | 84% | `prod_pilot_10pdf_2026_05_24_0010` |
| DeepSeek structure | 590.6s | 59.1s | 115.1s | 16% | `prod_pilot_10pdf_2026_05_24_0008` |
| Crop assets | 1.0s | 0.1s | 0.2s | 0% | `prod_pilot_10pdf_2026_05_24_0008` |
| Duplicate candidates | 0.6s | 0.1s | 0.1s | 0% | `prod_pilot_10pdf_2026_05_24_0008` |
| Save questions | 0.5s | 0.0s | 0.1s | 0% | `prod_pilot_10pdf_2026_05_24_0004` |

## Per-Paper Results

| Paper ID | Pages | Layout | Struct | Pass | Warn | Fail | Assets | Links | Status | Elapsed |
|----------|-------|--------|--------|------|------|------|--------|-------|--------|---------|
| `prod_pilot_10pdf_2026_05_24_0001` | 3 | 21 | 21 | 21 | 0 | 0 | 1 | 1 | completed | 174.0s |
| `prod_pilot_10pdf_2026_05_24_0002` | 4 | 21 | 21 | 20 | 1 | 0 | 1 | 1 | completed | 259.3s |
| `prod_pilot_10pdf_2026_05_24_0003` | 6 | 21 | 21 | 20 | 1 | 0 | 2 | 2 | completed | 205.1s |
| `prod_pilot_10pdf_2026_05_24_0004` | 16 | 21 | 21 | 20 | 1 | 0 | 6 | 6 | completed | 581.7s |
| `prod_pilot_10pdf_2026_05_24_0005` | 8 | 17 | 17 | 15 | 2 | 0 | 6 | 6 | completed | 199.5s |
| `prod_pilot_10pdf_2026_05_24_0006` | 23 | 18 | 18 | 18 | 0 | 0 | 12 | 12 | completed | 524.9s |
| `prod_pilot_10pdf_2026_05_24_0007` | 6 | 18 | 18 | 16 | 2 | 0 | 7 | 7 | completed | 174.8s |
| `prod_pilot_10pdf_2026_05_24_0008` | 24 | 37 | 37 | 35 | 2 | 0 | 20 | 20 | completed | 665.9s |
| `prod_pilot_10pdf_2026_05_24_0009` | 6 | 25 | 25 | 25 | 0 | 0 | 8 | 8 | completed | 179.6s |
| `prod_pilot_10pdf_2026_05_24_0010` | 23 | 25 | 25 | 25 | 0 | 0 | 16 | 16 | completed | 696.9s |

## Manifest

| Metric | Value |
|--------|-------|
| Completed entries | 10 |
| Attempts | 1 each |

## Verdict

PASS for 10-PDF production pilot.

The production path remained stable across long and short PDFs: MinerU, Layout
Ownership, DeepSeek structuring, PostgreSQL persistence, asset identification,
crop/store, pHash, duplicate candidates, and visual candidates.

The dominant bottleneck is MinerU at 84% of wall clock. DeepSeek is second at
16%. Database and asset post-processing overhead is effectively negligible.

## Notes

- Environment used `MINERU_MODEL_SOURCE=modelscope`.
- MinerU emitted transient polling timeout warnings on long PDFs but completed
  successfully without batch failure.
- Generated run artifacts remain under ignored paths: `data/runs/` and
  `data/assets/`.
- The generated generic report path `docs/eval/batch-2026-05-24.md` was not
  kept because future same-day batch runs overwrite that filename.

