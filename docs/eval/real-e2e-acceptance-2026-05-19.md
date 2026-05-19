# Real DeepSeek Non-Dry-Run E2E Acceptance — 2026-05-19

## Summary

This run validates the full ingestion path with real DeepSeek and real
PostgreSQL writes. MinerU artifacts were reused with `--resume`; all downstream
steps ran against fresh paper IDs.

| Metric | Value |
|--------|-------|
| Total PDFs | 3 |
| Completed | 3 |
| Partial | 0 |
| Failed | 0 |
| Success rate | 100.0% |
| Structured questions | 63 |
| Questions passed | 61 |
| Questions warning | 2 |
| Questions failed | 0 |
| Warning rate | 3.2% |
| Paper prefix | adr019_real_e2e |
| DeepSeek | real |
| Database | PostgreSQL non-dry-run |

## Quality Warning Distribution

| Warning Code | Count |
|--------------|-------|
| too_few_choices | 2 |

## Asset Metrics

| Metric | Value |
|--------|-------|
| raw_assets rows | 4 |
| question_asset_links | 4 |
| Crop successes | 4 |
| Crop failures | 0 |
| pHash computed | 4 |
| Unlinked raw_assets | 0 |
| Links without question_block | 0 |

## DB Integrity Checks

| Check | Value |
|-------|-------|
| papers rows | 3 |
| question_blocks rows | 63 |
| questions rows | 63 |
| raw_assets rows | 4 |
| question_asset_links rows | 4 |
| cropped assets with storage_url/content_hash | 4 |
| assets with perceptual_hash | 4 |
| unlinked raw_assets | 0 |
| links without question_block | 0 |

## Per-Paper Results

| Paper ID | Layout Q | Structured | Passed | Warning | Failed | Raw Assets | Links | Crop OK | pHash | Status |
|----------|----------|------------|--------|---------|--------|------------|-------|---------|-------|--------|
| adr019_real_e2e_paper_0001 | 21 | 21 | 21 | 0 | 0 | 1 | 1 | 1 | 1 | completed |
| adr019_real_e2e_paper_0002 | 21 | 21 | 20 | 1 | 0 | 1 | 1 | 1 | 1 | completed |
| adr019_real_e2e_paper_0003 | 21 | 21 | 20 | 1 | 0 | 2 | 2 | 2 | 2 | completed |

## Step Coverage

For each paper:

- `mineru_parse`: skipped via `--resume`
- `layout_ownership`: success
- `deepseek_structure`: success with real DeepSeek
- `save_questions`: success
- `identify_assets`: success
- `crop_assets`: success
- `store_assets`: success
- `compute_phash`: success
- `duplicate_candidates`: success
- `visual_candidates`: success

## Conclusion

**PASS** — Real DeepSeek + non-dry-run PostgreSQL ingestion is ready for
small-scale beta ingestion. The remaining warnings are non-blocking
`too_few_choices` cases and should be routed to review rather than blocking the
pipeline.

