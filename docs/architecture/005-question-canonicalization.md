# ADR 005: Question Canonicalization v1

## Status

Proposed — canonical layer on top of duplicate review decisions (2026-05-17).

## Problem

ADR 004 produces duplicate candidate groups and records human decisions. When a human
marks a group as "same", the system must produce a single **canonical question** that
represents all variants in the question bank. Raw questions must never be deleted or
overwritten, and canonicalization must be fully reversible.

## Decision

Add a canonicalization layer with three new tables. The only entry point is
`review_decision(decision='same')`. Representative selection is deterministic
(highest avg composite similarity, tie-break by source_position_key).
All operations are idempotent.

### Schema

```
canonical_questions         — one row per canonical question
question_variants           — links canonical to raw candidate items
canonicalization_events     — audit log (created, reverted, reactivated)
```

### Representative Selection

1. Compute pairwise composite similarity for all items in the group
2. For each item i, compute average composite similarity to all peers j ≠ i
3. Select item with max average; tie-break by min `source_position_key`

The similarity function uses the same weights as ADR 004:
- text_match: 0.25 (exact text fingerprint match)
- latex_match: 0.35 (exact LaTeX fingerprint match)
- asset_match: 0.25 (exact asset signature match)
- section_jaccard: 0.15 (section path Jaccard similarity)

### Idempotency

- `canonical_id` is deterministic: `cqn_{sha256(group_id)[:16]}`
- Variant IDs: `{canonical_id}_var_{item_block_id}`
- Create event ID: `{canonical_id}_evt_created`
- Rollback/reactivation event IDs append a UTC timestamp so repeated
  lifecycle events remain auditable instead of being collapsed by idempotent
  inserts.
- Re-running canonicalize on the same group:
  - If canonical exists and is active → return existing (no-op)
  - If canonical exists and is reverted → reactivate (status=active, variants active, event=reactivated)
  - If no canonical exists → create new

### Rollback

```
canonical_questions.status → 'reverted'
question_variants.is_active → false
canonicalization_events     → INSERT 'reverted' event
```

Reactivate by re-running canonicalize on the same group.

## Consequences

- Canonical layer is fully independent of raw questions
- Rollback is a single status change, not a delete
- Representative selection is deterministic and reproducible
- No auto-merge from fingerprint collisions
- All canonical generation is idempotent
