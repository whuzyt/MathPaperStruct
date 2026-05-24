# Production Smoke Test — 2026-05-24

## Summary

| Metric | Value |
|--------|-------|
| Tool | `tools/batch_real_ingest.py` |
| Mode | non-dry-run |
| PDF | `data/beta/pdf/paper_0029.pdf` |
| Pages | 2 |
| Status | completed |
| Success rate | 100.0% |
| Wall clock | 120.6s |

## Results

| Metric | Value |
|--------|-------|
| Layout questions | 10 |
| Structured questions | 10 |
| Questions passed | 10 |
| Questions warning | 0 |
| Questions failed | 0 |
| Raw assets | 2 |
| Question-asset links | 2 |
| Crop success | 2 |
| Crop failed | 0 |
| pHash computed | 2 |

## Step Timing

| Step | Time |
|------|------|
| MinerU parse | 97.0s |
| DeepSeek structure | 23.4s |
| Crop assets | 0.1s |
| Other DB/asset steps | < 0.1s each |

## Throughput

| Metric | Value |
|--------|-------|
| sec/PDF | 120.6s |
| sec/page | 60.3s |
| sec/question | 12.1s |

## Notes

- `--preflight-only` passed after starting Docker PostgreSQL and initializing schema.
- HuggingFace direct model fetch stalled at `Fetching 13 files: 0%`; rerun with `MINERU_MODEL_SOURCE=modelscope` succeeded.
- The smoke verified the full non-dry-run chain: MinerU, Layout Ownership, DeepSeek, PostgreSQL saves, raw asset linkage, crop/store, pHash, duplicate candidates, visual candidates.
- Generated run artifacts remain under ignored paths: `data/runs/` and `data/assets/`.

