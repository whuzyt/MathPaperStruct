# ADR 009: Paper Ingestion Orchestrator v1

## Status

Proposed — end-to-end pipeline orchestrator for single-paper ingestion (2026-05-17).

## Problem

The system has accumulated seven independent CLI subcommands for paper ingestion:

```
ingest                    — MinerU + DeepSeek
review asset generate     — raw_asset identification
review asset crop         — PDF crop + local storage
review asset phash        — perceptual hashing
review asset visual-candidates — visual dedup
review duplicate generate — question dedup
review canonicalize generate — canonical questions
```

Each must be run manually in the correct order, with the correct arguments, and
checking for errors between steps. A single paper requires 5+ manual CLI
invocations to go from PDF to review-ready state.

ADR 009 introduces a single orchestrator that chains these steps into one
command and produces a structured run report.

## Decision

Add `question-bank paper ingest-full` that executes the full pipeline:

```
1. MinerU parse          (critical)
2. Layout ownership      (critical)
3. DeepSeek structuring  (critical)
4. Save questions/blocks (critical)
5. Identify raw assets   (critical)
6. Crop assets           (non-critical)
7. Store assets locally  (non-critical)
8. Compute pHash         (non-critical)
9. Duplicate candidates  (non-critical, cross-paper)
10. Visual candidates    (non-critical, cross-paper)
11. Emit run report      (always)
```

Critical steps halt on failure. Non-critical steps log warnings and continue.

### CLI

```
question-bank paper ingest-full \
  --paper-id <paper_id> \
  --pdf <paper.pdf> \
  --work-dir data/runs/<paper_id> \
  --asset-dir data/assets \
  --dry-run \
  --resume
```

### Dry Run

`--dry-run` skips all database writes but still runs MinerU, layout ownership,
and DeepSeek structuring. Produces a run report showing what would have been
saved.

### Resume

`--resume` skips steps whose output already exists:
- `work_dir/output.md` and `work_dir/output.json` both exist → skip MinerU
- Raw assets exist in DB for this paper → skip asset identification
- Crop file exists on disk → skip individual crop
- pHash non-empty → skip individual pHash

### Run Report

Written to `{work_dir}/run-report.json`:

```json
{
  "paper_id": "paper_001",
  "status": "completed",
  "started_at": "2026-05-17T10:00:00Z",
  "finished_at": "2026-05-17T10:05:00Z",
  "steps": [
    {
      "name": "mineru_parse",
      "status": "success",
      "started_at": "...",
      "finished_at": "...",
      "input_count": 1,
      "output_count": 1,
      "error": null,
      "warnings": []
    }
  ],
  "counts": {
    "pages": 8,
    "questions": 25,
    "raw_assets": 12,
    "assets_cropped": 10,
    "assets_phash": 10,
    "duplicate_groups": 2,
    "visual_groups": 1
  },
  "warnings": [],
  "errors": []
}
```

### Failure Strategy

| Step | Critical | On Failure |
|------|----------|-----------|
| mineru_parse | yes | Stop pipeline |
| layout_ownership | yes | Stop pipeline |
| deepseek_structure | yes | Stop pipeline |
| save_questions | yes | Stop pipeline |
| identify_assets | yes | Stop pipeline |
| crop_assets | no | Record warning, continue |
| store_assets | no | Record warning, continue |
| compute_phash | no | Record warning, continue |
| duplicate_candidates | no | Record warning, continue |
| visual_candidates | no | Record warning, continue |

Partial crop/phash failures record which assets failed but do not abort the
entire step.

## Consequences

- Single command replaces 5+ manual CLI invocations
- Run report provides audit trail for each ingestion
- Resume support enables recovery from transient failures
- Dry run enables preview before committing to database
- Orchestrator is a thin coordinator — all algorithms remain in their
  respective service modules
- No new tables required in v1 (JSON report only)
