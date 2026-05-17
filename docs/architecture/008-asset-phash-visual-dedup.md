# ADR 008: Asset pHash & Visual Dedup v1

## Status

Proposed — perceptual hashing + visual duplicate candidates (2026-05-17).

## Problem

ADR 007 made assets real: cropped PNGs with bytes-based `content_hash`. But two
papers sharing the same geometry diagram have different `content_hash` values because
the images sit at different positions on different pages. Bytes-identical detection
only catches exact re-uploads of the same PDF element.

ADR 008 adds perceptual hashing to detect **visually similar** images across papers,
even when pixels differ slightly due to scaling, compression, or PDF rendering
differences.

## Decision

Use **average hash (aHash)** via Pillow: resize to 8×8 grayscale, threshold against
the mean pixel value. This produces a 64-bit hash (16 hex chars). Compare hashes with
**hamming distance** — XOR count of differing bits.

### Algorithm

1. Open image with Pillow, convert to L (grayscale)
2. Resize to 8×8 pixels (LANCZOS)
3. Compute mean pixel value across 64 pixels
4. Each pixel ≥ mean → 1, else 0
5. Pack into 64-bit integer, format as 16-char hex

### Visual Dedup

Pairwise hamming distance on all assets with non-empty `perceptual_hash`:
- Same `asset_type` only
- Different papers only
- Distance ≤ threshold (default 8)
- Greedy clustering by smallest distance first
- Each asset in at most one group
- Groups with ≥2 distinct papers become `VisualAssetCandidateGroup`

### Schema

No new tables. `raw_assets.perceptual_hash` (already exists from ADR 006) is
populated with the aHash hex string.

### V1 Limitations

- **aHash only**: no wavelet hash (wHash), no difference hash (dHash)
- **No rotation invariance**: 90° rotation produces entirely different hash
- **No CLIP/embeddings**: semantic similarity is out of scope
- **Candidate discovery only**: groups are printed, not auto-saved to DB
- **Single hash size**: 8×8 only, not configurable per asset

## Consequences

- `perceptual_hash` becomes populated (was empty since ADR 006)
- Visual similarity can now be detected across papers with different positions
- Pipeline: crop (ADR 007) → pHash (ADR 008) → visual dedup candidates
- Same candidate model as ADR 004: human reviews before any canonical merge
- Pillow becomes a required dependency for asset processing
