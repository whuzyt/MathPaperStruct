# Local Smoke Test — Paper Ingestion Orchestrator

Verifies that `paper ingest-full` can process a real PDF end-to-end using
MinerU 3.1.14 and a local DeepSeek client.

## Prerequisites

- Python 3.11+ with project venv activated
- MinerU 3.1.14 installed and on PATH (or set `MINERU_COMMAND`)
- DeepSeek API key (only if `--use-real-deepseek` is passed)
- A small PDF file (preferably 1–3 pages, math exam content)

## Environment

```bash
cd "/path/to/MathPaperStruct"

# Use project venv
source .venv/bin/activate

# Set MinerU path if not on PATH
export MINERU_COMMAND=".venv/bin/mineru"

# Set DeepSeek key only if testing with --use-real-deepseek
export DEEPSEEK_API_KEY="sk-..."
```

## Quick Smoke (Fake DeepSeek, No DB Write)

Uses `FakeDeepSeekClient` (returns fixed structs) and skips all DB writes.
This tests the MinerU → Layout Ownership → DeepSeek structuring chain
without requiring a database or DeepSeek credentials.

```bash
MINERU_COMMAND=".venv/bin/mineru" \
PYTHONPATH=src python3 -m question_bank.cli paper ingest-full \
  --paper-id smoke_001 \
  --pdf <path-to-small-pdf> \
  --work-dir data/runs/smoke_001 \
  --asset-dir data/assets \
  --dry-run
```

## Real DeepSeek Smoke (No DB Write)

Same as above but uses the real DeepSeek API. Good for catching prompt
compatibility issues before writing to the database.

```bash
MINERU_COMMAND=".venv/bin/mineru" \
DEEPSEEK_API_KEY="sk-..." \
PYTHONPATH=src python3 -m question_bank.cli paper ingest-full \
  --paper-id smoke_002 \
  --pdf <path-to-small-pdf> \
  --work-dir data/runs/smoke_002 \
  --asset-dir data/assets \
  --dry-run \
  --use-real-deepseek
```

## Resume (Idempotent Re-run)

After a successful first run, run again with `--resume`. MinerU should be
skipped (both `output.md` and `output.json` artifacts already exist).

```bash
MINERU_COMMAND=".venv/bin/mineru" \
PYTHONPATH=src python3 -m question_bank.cli paper ingest-full \
  --paper-id smoke_001 \
  --pdf <path-to-small-pdf> \
  --work-dir data/runs/smoke_001 \
  --asset-dir data/assets \
  --dry-run \
  --resume
```

## How to Judge Success

Open `data/runs/<paper_id>/run-report.json`:

```json
{
  "paper_id": "smoke_001",
  "status": "partial",
  "steps": [
    {"name": "mineru_parse",        "status": "success", "input_count": 1, "output_count": 1},
    {"name": "layout_ownership",    "status": "success"},
    {"name": "deepseek_structure",  "status": "success"},
    {"name": "save_questions",      "status": "skipped"},
    {"name": "identify_assets",     "status": "skipped"},
    {"name": "crop_assets",         "status": "skipped"},
    {"name": "store_assets",        "status": "skipped"},
    {"name": "compute_phash",       "status": "skipped"},
    {"name": "duplicate_candidates","status": "skipped"},
    {"name": "visual_candidates",   "status": "skipped"}
  ],
  "counts": {
    "steps_total": 10,
    "steps_succeeded": 3,
    "steps_warning": 0,
    "steps_failed": 0,
    "steps_skipped": 7
  },
  "warnings": [],
  "errors": []
}
```

**Critical checks**:
- `mineru_parse.status` = `success` — MinerU ran and produced artifacts
- `layout_ownership.status` = `success` — Layout blocks assigned
- `deepseek_structure.status` = `success` — DeepSeek structured the blocks
- `steps_succeeded` = 3 (mineru, layout, deepseek)
- `steps_skipped` = 7 (everything after save_questions in dry-run mode)
- `errors` is empty

Also check that `data/runs/<paper_id>/` contains the MinerU artifacts
(`<pdf_name>.md`, `<pdf_name>_middle.json`, `images/` inside a nested
subdirectory).

## Common Failures

### 1. First-time Model Download

MinerU 3.1.14 downloads models on first run (~2–5 GB). This can take
several minutes with no progress output visible through the orchestrator.
The process may appear hung — check Activity Monitor or `ps aux | grep mineru`
to confirm it's still running.

If models fail to download, check network access and retry. MinerU
downloads from HuggingFace or ModelScope depending on your region.

### 2. Local API Bind Failure

MinerU 3.1.14 starts a temporary local `mineru-api` service. If port
binding fails, you may see:

```
PermissionError: [Errno 1] Operation not permitted
```

Causes:
- macOS sandbox or firewall blocking `sock.bind`
- Port already in use

Mitigations:
- Run outside any application sandbox
- Check `lsof -i :<port>` for port conflicts
- Use `--api-url http://localhost:XXXX` with a pre-running mineru-api

### 3. Output Artifact Path Changes

MinerU 3.x nests output differently from older versions:
- **MinerU 2.x / magic-pdf**: `output_dir/output.md`, `output_dir/output.json`
- **MinerU 3.1.14 (pipeline)**: `output_dir/<pdf_name>/auto/<pdf_name>.md`
- **MinerU 3.1.14 (hybrid)**: `output_dir/<pdf_name>/hybrid_auto/<pdf_name>.md`

The orchestrator's artifact discovery uses `rglob` to find files regardless
of nesting depth. If you see `mineru_parse` `output_count: 0`, check whether
the glob patterns match your MinerU version's output. Common pattern mismatches:

| Expected | MinerU Produces | Fix |
|----------|----------------|-----|
| `<pdf_name>.md` | `output.md` | Already handled by `rglob` fallback |
| `<pdf_name>_middle.json` | Another `.json` filename | Already handled by `*.json` fallback |

If the artifact discovery still can't find the files, check the MinerU
output directory manually and adjust `mineru.py` glob patterns.

### 4. DeepSeek API Issues

With `--use-real-deepseek`:
- **401**: Invalid or missing `DEEPSEEK_API_KEY`
- **429**: Rate limited — wait and retry
- **500**: DeepSeek service error — retry later
- **Timeout**: Large blocks of text may time out — check network

The orchestrator records the exact error in `run-report.json` under the
`deepseek_structure` step's `error` field.

### 5. Layout Ownership with Unusual PDFs

PDFs with non-standard question numbering, mixed single/multi-column layouts,
or heavy use of inline images may produce unexpected block assignments.
Check `layout_ownership.status` — if `success` but `output_count` is 0,
the MinerU elements may not have recognizable question patterns.

This is expected for non-exam PDFs. Use a math exam PDF for meaningful results.
