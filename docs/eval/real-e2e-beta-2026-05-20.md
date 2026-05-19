# Real E2E Ingestion Beta — 2026-05-20

## Summary

This run validates full-batch real ingestion: 20 PDFs, real DeepSeek,
non-dry-run PostgreSQL writes, with complete asset pipeline (crop,
pHash, duplicate candidates, visual candidates).

| Metric | Value |
|--------|-------|
| Total PDFs | 20 |
| Pipeline completed | 20 |
| Pipeline partial | 0 |
| Pipeline failed | 0 |
| Success rate (completed + partial) | 100.0% |
| Total structured questions | 472 |
| Questions passed | 447 |
| Questions warning | 25 |
| Questions failed | 0 |
| Pass rate | 94.7% |
| Warning rate | 5.3% |
| Total elapsed | 7244s |
| Avg per PDF | 362.2s |

## Asset Pipeline Summary

| Metric | Value |
|--------|-------|
| PDFs with raw_assets | 20 of 20 |
| Total raw_assets | 187 |
| Total question_asset_links | 187 |
| Unlinked raw_assets | 0 |
| Links without question_block | 0 |
| Crop successes | 187 |
| Crop failures | 0 |
| Crop success rate | 100.0% |
| pHash computed | 187 |
| pHash success rate | 100.0% |
| Duplicate candidate groups | 1589 |
| Visual candidate groups | 512 |

## Per-Paper Results

| Paper ID | Pg | Layout | Struct | Pass | Warn | Fail | Assets | Links | CropOK | CropFail | pHash | Dup | Vis | Status |
|----------|----|--------|--------|------|------|------|--------|-------|--------|----------|-------|-----|-----|--------|
| real_beta_2026_05_19_0001 | 3 | 21 | 21 | 21 | 0 | 0 | 1 | 1 | 1 | 0 | 1 | 76 | 13 | completed |
| real_beta_2026_05_19_0002 | 4 | 21 | 21 | 20 | 1 | 0 | 1 | 1 | 1 | 0 | 1 | 76 | 13 | completed |
| real_beta_2026_05_19_0003 | 6 | 21 | 21 | 20 | 1 | 0 | 2 | 2 | 2 | 0 | 2 | 76 | 13 | completed |
| real_beta_2026_05_19_0004 | 16 | 21 | 21 | 21 | 0 | 0 | 6 | 6 | 6 | 0 | 6 | 76 | 13 | completed |
| real_beta_2026_05_19_0005 | 8 | 17 | 17 | 15 | 2 | 0 | 6 | 6 | 6 | 0 | 6 | 76 | 13 | completed |
| real_beta_2026_05_19_0006 | 23 | 18 | 18 | 18 | 0 | 0 | 12 | 12 | 12 | 0 | 12 | 76 | 13 | completed |
| real_beta_2026_05_19_0007 | 6 | 18 | 18 | 16 | 2 | 0 | 7 | 7 | 7 | 0 | 7 | 76 | 13 | completed |
| real_beta_2026_05_19_0008 | 24 | 37 | 37 | 35 | 2 | 0 | 20 | 20 | 20 | 0 | 20 | 92 | 20 | completed |
| real_beta_2026_05_19_0009 | 6 | 25 | 25 | 25 | 0 | 0 | 8 | 8 | 8 | 0 | 8 | 76 | 20 | completed |
| real_beta_2026_05_19_0010 | 23 | 25 | 25 | 25 | 0 | 0 | 16 | 16 | 16 | 0 | 16 | 76 | 24 | completed |
| real_beta_2026_05_19_0011 | 6 | 24 | 24 | 23 | 1 | 0 | 3 | 3 | 3 | 0 | 3 | 77 | 24 | completed |
| real_beta_2026_05_19_0012 | 23 | 23 | 23 | 22 | 1 | 0 | 6 | 6 | 6 | 0 | 6 | 81 | 55 | completed |
| real_beta_2026_05_19_0013 | 5 | 22 | 22 | 21 | 1 | 0 | 5 | 5 | 5 | 0 | 5 | 79 | 24 | completed |
| real_beta_2026_05_19_0014 | 21 | 23 | 23 | 23 | 0 | 0 | 15 | 15 | 15 | 0 | 15 | 79 | 25 | completed |
| real_beta_2026_05_19_0015 | 5 | 17 | 17 | 16 | 1 | 0 | 7 | 7 | 7 | 0 | 7 | 79 | 25 | completed |
| real_beta_2026_05_19_0016 | 26 | 34 | 34 | 30 | 4 | 0 | 22 | 22 | 22 | 0 | 22 | 94 | 32 | completed |
| real_beta_2026_05_19_0017 | 7 | 18 | 18 | 18 | 0 | 0 | 7 | 7 | 7 | 0 | 7 | 81 | 32 | completed |
| real_beta_2026_05_19_0018 | 25 | 20 | 20 | 19 | 1 | 0 | 15 | 15 | 15 | 0 | 15 | 81 | 44 | completed |
| real_beta_2026_05_19_0019 | 6 | 21 | 21 | 18 | 3 | 0 | 8 | 8 | 8 | 0 | 8 | 81 | 44 | completed |
| real_beta_2026_05_19_0020 | 28 | 46 | 46 | 41 | 5 | 0 | 20 | 20 | 20 | 0 | 20 | 81 | 52 | completed |

## Quality Warning Distribution

| Warning Code | Count |
|--------------|-------|
| answer_not_in_choices | 14 |
| too_few_choices | 11 |
| deepseek_fallback | 5 |

## Conclusion

### Acceptance Gates

| Gate | Threshold | Actual | Status |
|------|-----------|--------|--------|
| Completed + partial ≥ 90% | ≥ 18 | 20 of 20 (100.0%) | **PASS** |
| Pipeline failed = 0 | 0 | 0 | **PASS** |
| Questions failed = 0 | 0 | 0 | **PASS** |
| Warning rate ≤ 10% | ≤ 10% | 5.3% | **PASS** |
| raw_assets > 0 on ≥ 50% PDFs | ≥ 50% | 20 of 20 (100.0%) | **PASS** |
| question_asset_links > 0 | > 0 | 187 | **PASS** |
| Unlinked raw_assets ≤ 10% | ≤ 10% | 0.0% | **PASS** |
| Links without question_block = 0 | 0 | 0 | **PASS** |
| Crop success ≥ 80% | ≥ 80% | 100.0% | **PASS** |
| pHash success ≥ 80% | ≥ 80% | 100.0% | **PASS** |

**PASS** — All acceptance gates passed. Ready for full-scale production ingestion.
