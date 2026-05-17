# ADR 004: Duplicate Review Queue v1

## Status

Proposed — read-only exporter + review queue schema for human review (2026-05-17).

## Problem

ADR 003 detects fingerprint collisions — 217 fingerprints appear in ≥2 papers across
106 real papers. But a fingerprint collision is a *signal*, not a *decision*. Two
questions can share the exact same text but be different (same formula, different
context), or share only LaTeX formulas but be the same question (formatting variations).

The pipeline needs a human-reviewable queue where:
- Fingerprint collisions are surfaced as *candidate groups*
- Pairwise similarity scores help humans prioritize
- Decisions (same/variant/unrelated/unsure) are recorded idempotently
- All merge actions are reversible (append-only, no destructive updates)

## Decision

Add three new tables and a read-only exporter that generates candidate groups from
ADR 003 fingerprint collisions. No auto-merge. All decisions are append-only.

### Schema

```
duplicate_candidate_groups   — one row per fingerprint collision (≥2 papers)
duplicate_candidate_items    — links groups to individual blocks/questions
duplicate_review_decisions   — human decisions, append-only, idempotent
```

### Candidate Group Generation

```python
def generate_candidate_groups(
    identities_by_paper: dict[str, list[QuestionIdentity]],
    *,
    min_candidates: int = 2,
    max_items_per_group: int = 20,
    fingerprint_type: str = "text",
) -> list[DuplicateCandidateGroup]:
```

Groups are formed by exact fingerprint match (default: text_fingerprint). Within each
group, pairwise similarity is computed across 5 dimensions:

| Dimension | Weight | Meaning |
|-----------|--------|---------|
| text_match | 0.25 | Same full text (always 1.0 for text-fingerprint groups) |
| latex_match | 0.35 | Same LaTeX formulas |
| asset_match | 0.25 | Same figures/tables at same positions |
| section_jaccard | 0.15 | Section path overlap (structural context) |
| **composite** | — | Weighted sum, 0.0–1.0 |

Groups are trimmed to `max_items_per_group` by average composite similarity,
keeping the most representative items.

### Review Decisions

```python
@dataclass(slots=True)
class ReviewDecision:
    group_id: str
    decision: str              # "same" | "variant" | "unrelated" | "unsure"
    canonical_question_id: str | None
    reviewer: str
    reason: str
```

Decisions are idempotent: `ON CONFLICT DO NOTHING`. Re-submitting the same
(group_id, decision, reviewer, date) is a no-op. Decisions are never modified
or deleted, only appended.

### Deterministic Group IDs

Group IDs are `dcg_{sha256(fingerprint)[:16]}` — regenerating the same fingerprint
produces the same group ID. Combined with `ON CONFLICT DO UPDATE`, re-running
candidate generation is safe.

## Scope

- **In scope**: Schema migration (3 tables), candidate group generator, pairwise similarity, batch exporter tool, CLI review commands, idempotent decision recording
- **Out of scope**: Auto-merge, automatic canonical question selection, modifying existing question tables, DeepSeek integration, UI

## Implementation File

```text
src/question_bank/services/duplicate_review.py
```
