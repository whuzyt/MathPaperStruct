# ADR 003: Question Identity & Dedup v1

## Status

Proposed — read-only fingerprinting for duplicate detection (2026-05-17).

## Problem

ADR 001 and ADR 002 define deterministic question extraction: each paper produces
`LayoutOwnershipBlock` objects identified by `paper_id + section_path + question_number`.
But when the pipeline ingests multiple papers, the same question may appear under
different `paper_id` and `question_number` combinations:

- Paper A question "1" and Paper B question "5" could be the exact same question
- Mock exam papers often share questions with gaokao past papers
- Without identity, the question bank would store duplicates with no way to detect them

ADR 002 solved "where does a question belong" (section_path). ADR 003 addresses
"is this the same question" (identity).

## Decision

Add a **read-only** fingerprinting module (`question_identity.py`) that generates
identity keys for each `LayoutOwnershipBlock`. It does NOT modify the main pipeline,
does NOT write to DB, and does NOT auto-merge. Output goes to the shadow batch
report for statistical analysis.

### Four Identity Dimensions

| Fingerprint | Purpose | Collision meaning |
|-------------|---------|-------------------|
| `source_position_key` | Where the question came from | Same paper + section + number = same source |
| `text_fingerprint` | Exact/near-exact content match | Same full text = likely same question |
| `latex_fingerprint` | Semantic match via LaTeX formulas | Same formulas = same math content |
| `asset_signature` | Same-question-with-same-figure | Same assets at same positions = same question |

### Fingerprint Construction

**source_position_key**: `{paper_id}#{section_path_joined_with_/}#{question_number}`

**text_fingerprint**: Join all owned text/formula element text → normalize whitespace → SHA256[:16]

**latex_fingerprint**: Extract `$...$` substrings from owned elements → normalize whitespace within each → sort alphabetically → join with ` | ` → SHA256[:16]

**asset_signature**: For each assigned asset, look up element by `asset_id` → `{type}:p{page}:{bbox_rounded}` → sort → join with ` | ` → SHA256[:16]

### Why Fingerprints, Not Hashing the Whole Block

- `text_fingerprint` ignores element structure differences (same text split differently across elements)
- `latex_fingerprint` is invariant to text surrounding the formulas (OCR noise, formatting)
- `asset_signature` captures spatial layout — same figure at same position = strong duplicate signal
- SHA-256 truncated to 16 hex chars (64 bits) gives sufficient collision resistance for ~10^6 questions

## Scope

- **In scope**: Read-only fingerprint generation, integration into shadow batch report, intra-paper and cross-paper collision statistics
- **Out of scope**: DB dedup table, automatic merge, pipeline integration, dedup UI

## Implementation File

```text
src/question_bank/services/question_identity.py
```
