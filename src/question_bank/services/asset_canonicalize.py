"""ADR 006: Asset Canonicalization v1 — Group raw_assets by content_hash.

Generates canonical asset candidates. In v1, content_hash is structural
(position + type), so groups only form on identical re-processing. v2 will
replace content_hash with image bytes hash for true cross-paper dedup.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(slots=True)
class CanonicalAsset:
    id: str
    asset_fingerprint: str
    representative_raw_asset_id: str
    asset_type: str
    storage_url: str | None
    perceptual_hash: str
    content_hash: str
    status: str


@dataclass(slots=True)
class AssetVariant:
    id: str
    canonical_asset_id: str
    raw_asset_id: str
    transform_json: str
    similarity: float | None
    is_active: bool


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def build_canonical_asset_id(content_hash: str) -> str:
    return f"ca_{_short_hash(content_hash)}"


def build_asset_fingerprint(raw_assets: list[dict]) -> str:
    content_hashes = sorted({ra.get("content_hash", "") for ra in raw_assets if ra.get("content_hash")})
    if not content_hashes:
        return ""
    return _short_hash(" | ".join(content_hashes))


def generate_canonical_asset_candidates(
    raw_assets: list[dict],
    *,
    min_candidates: int = 2,
) -> list[dict]:
    """Group raw_assets by content_hash. Returns list of {canonical, variants} dicts."""
    by_content_hash: dict[str, list[dict]] = {}
    for ra in raw_assets:
        ch = ra.get("content_hash", "")
        if not ch:
            continue
        by_content_hash.setdefault(ch, []).append(ra)

    candidates: list[dict] = []
    for content_hash, items in by_content_hash.items():
        # Filter to distinct papers
        papers = {item.get("paper_id", "") for item in items}
        if len(papers) < min_candidates:
            continue

        asset_types = {item.get("asset_type", "") for item in items}
        # Never cross asset_type
        if len(asset_types) > 1:
            continue

        canonical_id = build_canonical_asset_id(content_hash)
        fingerprint = build_asset_fingerprint(items)

        representative = items[0]  # same content_hash → all equivalent
        asset_type = items[0].get("asset_type", "")

        canonical = CanonicalAsset(
            id=canonical_id,
            asset_fingerprint=fingerprint,
            representative_raw_asset_id=representative.get("id", ""),
            asset_type=asset_type,
            storage_url=representative.get("storage_url"),
            perceptual_hash=representative.get("perceptual_hash", ""),
            content_hash=content_hash,
            status="active",
        )

        variants: list[AssetVariant] = []
        for item in items:
            variant = AssetVariant(
                id=f"{canonical_id}_var_{item.get('id', '')}",
                canonical_asset_id=canonical_id,
                raw_asset_id=item.get("id", ""),
                transform_json="{}",
                similarity=None,
                is_active=True,
            )
            variants.append(variant)

        candidates.append({
            "canonical": canonical,
            "variants": variants,
        })

    candidates.sort(key=lambda g: -len(g["variants"]))
    return candidates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
