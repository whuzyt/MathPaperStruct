# Asset Linkage Evaluation — 2026-05-18

## Summary

| Metric | Value |
|--------|-------|
| Total PDFs | 5 |
| Completed | 5 |
| Partial | 0 |
| Failed | 0 |
| Crashed (unhandled) | 0 |
| Success rate | 100.0% |
| Elapsed | 2s |
| Avg per PDF | 0.3s |
| Generated | 2026-05-18 11:37:46 |
| Paper prefix | asset_eval |

Note: elapsed time reflects the final post-fix `--resume` verification run.
The initial non-dry-run pass ran MinerU on all 5 PDFs and took 1249s; it
exposed the PyMuPDF crop API incompatibility fixed in this patch.

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

## Per-Paper Results

| Paper ID | Pages | Layout Q | M-Visual | RA | Links | Crop OK | Crop Fail | pHash | Unassgn | LowConf | Warn | Err | Status |
|----------|-------|----------|----------|----|-------|---------|-----------|-------|---------|---------|------|-----|--------|
| asset_eval_paper_0001 | 3 | 21 | 1 | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | completed |
| asset_eval_paper_0002 | 4 | 21 | 1 | 1 | 1 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | completed |
| asset_eval_paper_0003 | 6 | 21 | 2 | 2 | 2 | 2 | 0 | 2 | 0 | 0 | 0 | 0 | completed |
| asset_eval_paper_0004 | 16 | 21 | 6 | 6 | 6 | 6 | 0 | 6 | 0 | 4 | 0 | 0 | completed |
| asset_eval_paper_0005 | 8 | 17 | 6 | 6 | 6 | 6 | 0 | 6 | 0 | 1 | 0 | 0 | completed |

## Per-Paper Detail

### asset_eval_paper_0001

MinerU elements: image=1, list=2, page_number=3, text=48

- [SKIP] mineru_parse (in=0 out=0)
- [OK] layout_ownership (in=54 out=21)
- [OK] deepseek_structure (in=21 out=21)
- [OK] save_questions (in=21 out=21)
- [SKIP] identify_assets (in=0 out=1)
- [OK] crop_assets (in=1 out=1)
- [OK] store_assets (in=1 out=1)
- [OK] compute_phash (in=1 out=1)
- [OK] duplicate_candidates (in=101 out=25)
- [OK] visual_candidates (in=16 out=0)
- DB: 1 raw_assets, 1 links, 0 unassigned visual, 0 low-confidence
- Run report: `data/runs/asset_eval_2026-05-18/asset_eval_paper_0001/run-report.json`

### asset_eval_paper_0002

MinerU elements: equation=1, image=1, list=2, page_number=4, text=74

- [SKIP] mineru_parse (in=0 out=0)
- [OK] layout_ownership (in=82 out=21)
- [OK] deepseek_structure (in=21 out=21)
- [OK] save_questions (in=21 out=21)
- [SKIP] identify_assets (in=0 out=1)
- [OK] crop_assets (in=1 out=1)
- [OK] store_assets (in=1 out=1)
- [OK] compute_phash (in=1 out=1)
- [OK] duplicate_candidates (in=101 out=25)
- [OK] visual_candidates (in=16 out=1)
- DB: 1 raw_assets, 1 links, 0 unassigned visual, 0 low-confidence
- Run report: `data/runs/asset_eval_2026-05-18/asset_eval_paper_0002/run-report.json`

### asset_eval_paper_0003

MinerU elements: equation=1, image=2, list=3, page_number=6, text=54

- [SKIP] mineru_parse (in=0 out=0)
- [OK] layout_ownership (in=66 out=21)
- [OK] deepseek_structure (in=21 out=21)
- [OK] save_questions (in=21 out=21)
- [SKIP] identify_assets (in=0 out=1)
- [OK] crop_assets (in=2 out=2)
- [OK] store_assets (in=2 out=2)
- [OK] compute_phash (in=2 out=2)
- [OK] duplicate_candidates (in=101 out=25)
- [OK] visual_candidates (in=16 out=1)
- DB: 2 raw_assets, 2 links, 0 unassigned visual, 0 low-confidence
- Run report: `data/runs/asset_eval_2026-05-18/asset_eval_paper_0003/run-report.json`

### asset_eval_paper_0004

MinerU elements: equation=4, image=6, list=1, page_number=16, text=203

- [SKIP] mineru_parse (in=0 out=0)
- [OK] layout_ownership (in=230 out=21)
- [OK] deepseek_structure (in=21 out=21)
- [OK] save_questions (in=21 out=21)
- [SKIP] identify_assets (in=0 out=1)
- [OK] crop_assets (in=6 out=6)
- [OK] store_assets (in=6 out=6)
- [OK] compute_phash (in=6 out=6)
- [OK] duplicate_candidates (in=101 out=25)
- [OK] visual_candidates (in=16 out=3)
- DB: 6 raw_assets, 6 links, 0 unassigned visual, 4 low-confidence
- Run report: `data/runs/asset_eval_2026-05-18/asset_eval_paper_0004/run-report.json`

### asset_eval_paper_0005

MinerU elements: chart=1, equation=1, image=4, list=20, page_number=8, table=1, text=41

- [SKIP] mineru_parse (in=0 out=0)
- [OK] layout_ownership (in=76 out=17)
- [OK] deepseek_structure (in=17 out=17)
- [OK] save_questions (in=17 out=17)
- [SKIP] identify_assets (in=0 out=1)
- [OK] crop_assets (in=6 out=6)
- [OK] store_assets (in=6 out=6)
- [OK] compute_phash (in=6 out=6)
- [OK] duplicate_candidates (in=101 out=25)
- [OK] visual_candidates (in=16 out=3)
- DB: 6 raw_assets, 6 links, 0 unassigned visual, 1 low-confidence
- Run report: `data/runs/asset_eval_2026-05-18/asset_eval_paper_0005/run-report.json`

## Conclusion

**PASS** — 100.0% success rate, 100.0% crop success, 100.0% phash success. Ready for small-batch DB ingestion.
