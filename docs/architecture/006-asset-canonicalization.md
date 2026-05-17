# ADR 006: Asset Canonicalization & Crop Persistence v1

## Status

Proposed — asset identity layer + canonical candidate infrastructure (2026-05-17).

## Problem

ADR 001 produces `AssetAssignment` objects linking images/tables/figures to question
blocks. But these assignments exist only during pipeline runs — they are not persisted
as independent asset records. When two papers share the same diagram, there is no way
to track that the same image appears across papers.

ADR 006 builds the asset lifecycle infrastructure:
- Deterministic asset identity (`raw_asset_id`)
- Persistent raw asset records
- Question-to-asset links
- Canonical asset candidates (grouped by content hash)

## Decision

Add four new tables for asset identity and canonicalization. Use deterministic IDs.
Group by structural `content_hash` in v1 (will become image bytes hash in v2).

### Schema

```
raw_assets              — one row per image/table/figure element from MinerU
question_asset_links    — links raw_assets to questions (block_id or canonical)
canonical_assets        — one row per unique content_hash group
asset_variants          — links canonical_assets to their raw_asset members
```

### V1 Limitations

- **No image cropping**: `crop_path` is always null
- **No perceptual hash**: `perceptual_hash` is always empty
- **Content hash is structural**: based on page + bbox + type, not image bytes
- **Canonical groups are sparse**: only same-element re-processing produces groups
- **Full image dedup**: deferred to ADR 007

### Raw Asset ID

```
ra_{sha256(paper_id:p{page}:bbox_rounded:asset_type:source_element_id)[:16]}
```

Same paper, element, page, bbox, and type → same ID. Different paper or different
position → different ID. Re-processing is idempotent.

### Content Hash

```
sha256(p{page}:bbox_rounded:asset_type)[:16]
```

In v2, this will change to `sha256(image_bytes)` to enable cross-paper dedup.
The schema column name stays the same; only the computation changes.

### Canonical Asset Candidate Generation

1. Group `raw_assets` by `content_hash`
2. Filter to groups with ≥2 distinct papers
3. Never cross `asset_type` boundaries
4. Build one `canonical_asset` per group
5. Build one `asset_variant` per raw_asset in the group

In v1, groups are rare because `content_hash` is position-based. The infrastructure
is ready for v2 where content_hash becomes image-based.

## Consequences

- Asset records become persistent and queryable
- Same-element re-processing is idempotent
- Schema supports future image bytes hashing without migration
- Canonical asset layer has same lifecycle as canonical questions (active/reverted)
- No actual image processing in v1
