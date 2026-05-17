"""ADR 006: Asset Identity v1 — Raw asset identification from LayoutOwnershipBlock.

Generates deterministic raw_asset records from AssetAssignment data.
Does NOT do image cropping, perceptual hashing, or content-based dedup (v2).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from question_bank.services.layout_ownership import (
    AssetAssignment,
    LayoutOwnershipBlock,
    _Element,
)


@dataclass(slots=True)
class RawAsset:
    id: str
    paper_id: str
    page: int
    bbox_json: str
    asset_type: str
    source_element_id: str
    crop_path: str | None
    storage_url: str | None
    perceptual_hash: str
    content_hash: str
    width: float | None
    height: float | None
    status: str


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def build_raw_asset_id(
    paper_id: str,
    page: int,
    bbox: tuple[float, float, float, float],
    asset_type: str,
    source_element_id: str,
) -> str:
    bbox_rounded = tuple(round(v, 4) for v in bbox)
    key = f"{paper_id}:p{page}:{bbox_rounded}:{asset_type}:{source_element_id}"
    return f"ra_{_short_hash(key)}"


def compute_content_hash(
    page: int,
    bbox: tuple[float, float, float, float],
    asset_type: str,
) -> str:
    bbox_rounded = tuple(round(v, 4) for v in bbox)
    key = f"p{page}:{bbox_rounded}:{asset_type}"
    return _short_hash(key)


def identify_raw_assets(
    paper_id: str,
    blocks: list[LayoutOwnershipBlock],
    elements_by_id: dict[str, _Element],
) -> tuple[list[RawAsset], list[dict]]:
    raw_assets: list[RawAsset] = []
    links: list[dict] = []

    for block in blocks:
        for asset in block.assets:
            elem = elements_by_id.get(asset.asset_id)
            if elem is None:
                continue

            ra_id = build_raw_asset_id(
                paper_id, elem.page, elem.bbox,
                elem.type, elem.id,
            )
            content_hash = compute_content_hash(elem.page, elem.bbox, elem.type)

            ra = RawAsset(
                id=ra_id,
                paper_id=paper_id,
                page=elem.page,
                bbox_json=json.dumps(
                    [round(v, 4) for v in elem.bbox], ensure_ascii=False
                ),
                asset_type=elem.type,
                source_element_id=elem.id,
                crop_path=None,
                storage_url=None,
                perceptual_hash="",
                content_hash=content_hash,
                width=round(elem.width, 4) if elem.width else None,
                height=round(elem.height, 4) if elem.height else None,
                status="active",
            )
            raw_assets.append(ra)

            link = {
                "id": f"qal_{ra_id}_{block.question_block_id}",
                "question_id": block.question_block_id,
                "canonical_question_id": None,
                "raw_asset_id": ra_id,
                "role": "figure",
                "confidence": round(asset.score, 4),
                "needs_review": asset.needs_review,
            }
            links.append(link)

    return raw_assets, links


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
