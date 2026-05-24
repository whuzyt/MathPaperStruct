# Production Pilot 3-PDF Batch — 2026-05-24

## Summary

| Metric | Value |
|--------|-------|
| Tool | `tools/batch_real_ingest.py` |
| Mode | non-dry-run |
| PDFs | 3 |
| Pages | 13 |
| Completed | 3 |
| Partial | 0 |
| Failed | 0 |
| Crashed | 0 |
| Success rate | 100.0% |
| Wall clock | 631.9s |

## Question Quality

| Metric | Value |
|--------|-------|
| Layout questions | 63 |
| Structured questions | 63 |
| Questions passed | 61 |
| Questions warning | 2 |
| Questions failed | 0 |

Warning distribution:

| Warning Code | Count |
|--------------|-------|
| `too_few_choices` | 1 |
| `answer_not_in_choices` | 1 |

## Asset Pipeline

| Metric | Value |
|--------|-------|
| Raw assets | 4 |
| Question-asset links | 4 |
| Crop success | 4 |
| Crop failed | 0 |
| pHash computed | 4 |

## Throughput

| Metric | Value |
|--------|-------|
| sec/PDF | 210.6s |
| sec/page | 48.6s |
| sec/question | 10.0s |

## Step Timing

| Step | Total | Avg | Max | Share |
|------|-------|-----|-----|-------|
| MinerU parse | 495.6s | 165.2s | 203.2s | 78% |
| DeepSeek structure | 136.4s | 45.5s | 50.7s | 22% |
| Crop assets | 0.2s | 0.1s | 0.1s | 0% |
| Save questions | 0.2s | 0.1s | 0.1s | 0% |

## Per-Paper Results

| Paper ID | Pages | Layout | Struct | Pass | Warn | Fail | Assets | Links | Status | Elapsed |
|----------|-------|--------|--------|------|------|------|--------|-------|--------|---------|
| `prod_pilot_2026_05_24_0001` | 3 | 21 | 21 | 21 | 0 | 0 | 1 | 1 | completed | 175.1s |
| `prod_pilot_2026_05_24_0002` | 4 | 21 | 21 | 20 | 1 | 0 | 1 | 1 | completed | 245.4s |
| `prod_pilot_2026_05_24_0003` | 6 | 21 | 21 | 20 | 1 | 0 | 2 | 2 | completed | 211.5s |

## Verdict

PASS for small production pilot.

The full non-dry-run chain remained stable across consecutive PDFs: MinerU,
Layout Ownership, DeepSeek structuring, PostgreSQL persistence, asset
identification, crop/store, pHash, duplicate candidates, and visual candidates.

The dominant bottleneck is still MinerU at 78% of wall clock. DeepSeek is the
second bottleneck at 22%, but did not create failures in this pilot.

## Notes

- Environment used `MINERU_MODEL_SOURCE=modelscope`; HuggingFace direct fetch
  had previously stalled during smoke testing.
- Generated run artifacts remain under ignored paths: `data/runs/` and
  `data/assets/`.
- The generated generic report path `docs/eval/batch-2026-05-24.md` was not
  kept because future same-day batch runs overwrite that filename.

