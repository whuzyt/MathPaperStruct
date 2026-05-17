# ADR 007: PDF Crop & Object Storage v1

## Status

Proposed — PDF crop + local asset store (2026-05-17).

## Problem

ADR 006 built the asset identity layer: `raw_assets`, `question_asset_links`,
`canonical_assets`, and `asset_variants`. But the key fields are empty:
- `crop_path` is always null
- `storage_url` is always null
- `perceptual_hash` is always empty
- `content_hash` is structural (page + bbox + type), not based on image content

Without actual image bytes, cross-paper dedup is impossible. Two papers sharing
the same diagram have different structural hashes because positions differ.

ADR 007 makes these fields real by cropping image/table/figure regions from PDF
pages, storing them to local disk, and computing content hashes from image bytes.

## Decision

Use **PyMuPDF (fitz)** for PDF rendering. Store crops to **local filesystem**
with deterministic paths. Compute `content_hash` as `SHA256(PNG bytes)[:16]`.

### Crop Pipeline

```
paper.pdf + raw_assets (from DB)
  → fitz.open(pdf)
  → for each raw_asset:
      - get page by raw_asset["page"] - 1
      - normalized bbox → pixel bbox (clamped to page)
      - validate bbox (non-zero area)
      - render page at 300 DPI → pixmap
      - crop region → PNG bytes
      - SHA256(PNG bytes) → content_hash
  → CropResult per asset
```

### Storage

```
CropResult
  → target = {root_dir}/assets/{paper_id}/{raw_asset_id}.png
  → write to .tmp, atomic rename
  → storage_url = local://assets/{paper_id}/{raw_asset_id}.png
  → update raw_assets row
```

### Status

- `active` — crop successful, fields populated
- `crop_failed` — crop failed, error recorded

No additional status values needed in v1.

### V1 Limitations

- **Local filesystem only**: no S3/MinIO/cloud storage
- **No perceptual hash**: `perceptual_hash` still empty (deferred to ADR 008)
- **No image similarity**: dedup still uses structural hash; image-based dedup
  will switch to `content_hash` from image bytes in ADR 008
- **No multi-process**: single-threaded PDF rendering
- **PyMuPDF required**: explicit error if `fitz` not installed, no fallback

## Consequences

- `raw_assets.crop_path` and `storage_url` become populated
- `content_hash` transitions from structural to image-based
- Schema unchanged from ADR 006 — no migration needed
- Deterministic paths enable idempotent re-processing
- Single-crop isolation prevents one broken asset from blocking a paper
