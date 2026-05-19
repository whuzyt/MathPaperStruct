# ADR 018 Asset Linkage Acceptance — 2026-05-19

This run validates the non-dry-run asset path using real PostgreSQL writes.
MinerU artifacts were reused with `--resume`; `paper_id` values used a fresh
`adr018_asset_eval` prefix so `identify_assets` regenerated `raw_assets` and
`question_asset_links` instead of reusing prior DB rows.

## Summary

| Metric | Value |
|--------|-------|
| Total PDFs | 5 |
| Completed | 5 |
| Partial | 0 |
| Failed | 0 |
| Crashed (unhandled) | 0 |
| Success rate | 100.0% |
| Elapsed | 4s |
| Avg per PDF | 0.8s |
| Generated | 2026-05-19 19:03:02 |
| Paper prefix | adr018_asset_eval |

## Asset Metrics (Aggregate)

| Metric | Total |
|--------|-------|
| MinerU visual elements (image+table+chart) | 16 |
| raw_assets rows | 16 |
| question_asset_links | 16 |
| Crop successes | 16 |
| Crop failures | 0 |
| pHash computed | 16 |
| Unassigned visual assets | 0 |
| Low-confidence links (<0.8) | 5 |

## DB Integrity Checks

| Check | Value |
|-------|-------|
| papers rows | 5 |
| question_blocks rows | 101 |
| questions rows | 101 |
| raw_assets rows | 16 |
| question_asset_links rows | 16 |
| cropped assets with storage_url/content_hash | 16 |
| assets with perceptual_hash | 16 |
| unlinked raw_assets | 0 |
| links without question_block | 0 |

## Per-Paper Results

| Paper ID | Pages | Layout Q | M-Visual | RA | Links | Crop OK | Crop Fail | pHash | Unassgn | LowConf | Warn | Err | Status |
|----------|-------|----------|----------|----|-------|---------|-----------|-------|---------|---------|------|-----|--------|
| adr018_asset_eval_paper_0001 | 3 | 21 | 1 | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | completed |
| adr018_asset_eval_paper_0002 | 4 | 21 | 1 | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | completed |
| adr018_asset_eval_paper_0003 | 6 | 21 | 2 | 2 | 2 | 2 | 0 | 2 | 0 | 0 | 0 | 0 | completed |
| adr018_asset_eval_paper_0004 | 16 | 21 | 6 | 6 | 6 | 6 | 0 | 6 | 0 | 4 | 0 | 0 | completed |
| adr018_asset_eval_paper_0005 | 8 | 17 | 6 | 6 | 6 | 6 | 0 | 6 | 0 | 1 | 0 | 0 | completed |

## Per-Paper Detail

### adr018_asset_eval_paper_0001

MinerU elements: image=1, list=2, page_number=3, text=48

- [SKIP] mineru_parse (in=0 out=0)
- [OK] layout_ownership (in=54 out=21)
- [OK] deepseek_structure (in=21 out=21)
- [OK] save_questions (in=21 out=21)
- [OK] identify_assets (in=21 out=1)
- [OK] crop_assets (in=1 out=1)
- [OK] store_assets (in=1 out=1)
- [OK] compute_phash (in=1 out=1)
- [OK] duplicate_candidates (in=122 out=40)
- [OK] visual_candidates (in=17 out=3)
- DB: 1 raw_assets, 1 links, 0 unassigned visual, 0 low-confidence
- Run report: `data/runs/asset_eval_2026-05-19/adr018_asset_eval_paper_0001/run-report.json`

### adr018_asset_eval_paper_0002

MinerU elements: equation=1, image=1, list=2, page_number=4, text=74

- [SKIP] mineru_parse (in=0 out=0)
- [OK] layout_ownership (in=82 out=21)
- [OK] deepseek_structure (in=21 out=21)
- [OK] save_questions (in=21 out=21)
- [OK] identify_assets (in=21 out=1)
- [OK] crop_assets (in=1 out=1)
- [OK] store_assets (in=1 out=1)
- [OK] compute_phash (in=1 out=1)
- [OK] duplicate_candidates (in=143 out=55)
- [OK] visual_candidates (in=18 out=3)
- DB: 1 raw_assets, 1 links, 0 unassigned visual, 0 low-confidence
- Run report: `data/runs/asset_eval_2026-05-19/adr018_asset_eval_paper_0002/run-report.json`

### adr018_asset_eval_paper_0003

MinerU elements: equation=1, image=2, list=3, page_number=6, text=54

- [SKIP] mineru_parse (in=0 out=0)
- [OK] layout_ownership (in=66 out=21)
- [OK] deepseek_structure (in=21 out=21)
- [OK] save_questions (in=21 out=21)
- [OK] identify_assets (in=21 out=2)
- [OK] crop_assets (in=2 out=2)
- [OK] store_assets (in=2 out=2)
- [OK] compute_phash (in=2 out=2)
- [OK] duplicate_candidates (in=164 out=57)
- [OK] visual_candidates (in=20 out=3)
- DB: 2 raw_assets, 2 links, 0 unassigned visual, 0 low-confidence
- Run report: `data/runs/asset_eval_2026-05-19/adr018_asset_eval_paper_0003/run-report.json`

### adr018_asset_eval_paper_0004

MinerU elements: equation=4, image=6, list=1, page_number=16, text=203

- [SKIP] mineru_parse (in=0 out=0)
- [OK] layout_ownership (in=230 out=21)
- [OK] deepseek_structure (in=21 out=21)
- [OK] save_questions (in=21 out=21)
- [OK] identify_assets (in=21 out=6)
- [OK] crop_assets (in=6 out=6)
- [OK] store_assets (in=6 out=6)
- [OK] compute_phash (in=6 out=6)
- [OK] duplicate_candidates (in=185 out=59)
- [OK] visual_candidates (in=26 out=7)
- DB: 6 raw_assets, 6 links, 0 unassigned visual, 4 low-confidence
- Run report: `data/runs/asset_eval_2026-05-19/adr018_asset_eval_paper_0004/run-report.json`

### adr018_asset_eval_paper_0005

MinerU elements: chart=1, equation=1, image=4, list=20, page_number=8, table=1, text=41

- [SKIP] mineru_parse (in=0 out=0)
- [OK] layout_ownership (in=76 out=17)
- [OK] deepseek_structure (in=17 out=17)
- [OK] save_questions (in=17 out=17)
- [OK] identify_assets (in=17 out=6)
- [OK] crop_assets (in=6 out=6)
- [OK] store_assets (in=6 out=6)
- [OK] compute_phash (in=6 out=6)
- [OK] duplicate_candidates (in=202 out=76)
- [OK] visual_candidates (in=32 out=13)
- DB: 6 raw_assets, 6 links, 0 unassigned visual, 1 low-confidence
- Run report: `data/runs/asset_eval_2026-05-19/adr018_asset_eval_paper_0005/run-report.json`

## Conclusion

**PASS** — 100.0% success rate, 100.0% crop success, 100.0% phash success. Ready for small-batch DB ingestion.
