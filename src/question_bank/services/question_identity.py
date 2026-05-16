"""ADR 003: Question Identity & Dedup v1 — Read-only fingerprinting.

Generates identity keys for LayoutOwnershipBlock without modifying the main
pipeline. Output is consumed by batch_shadow.py for duplicate detection stats.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from question_bank.services.layout_ownership import (
    AssetAssignment,
    LayoutOwnershipBlock,
    _Element,
)

LATEX_PATTERN = re.compile(r"\$(.+?)\$")


@dataclass(slots=True)
class QuestionIdentity:
    block_id: str
    source_position_key: str
    text_fingerprint: str
    latex_fingerprint: str
    asset_signature: str


def _short_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", "", text)


def build_source_position_key(
    paper_id: str,
    section_path: tuple[str, ...],
    question_number: str,
) -> str:
    path_str = "/".join(section_path)
    return f"{paper_id}#{path_str}#{question_number}"


def compute_text_fingerprint(
    block: LayoutOwnershipBlock,
    elements_by_id: dict[str, _Element],
) -> str:
    parts: list[str] = []
    for eid in block.element_ids:
        elem = elements_by_id.get(eid)
        if elem is None:
            continue
        if elem.type in ("text", "formula"):
            text = elem.text.strip()
            if text:
                parts.append(text)
    if not parts:
        return ""
    normalized = _normalize_whitespace(" ".join(parts))
    return _short_hash(normalized)


def compute_latex_fingerprint(
    block: LayoutOwnershipBlock,
    elements_by_id: dict[str, _Element],
) -> str:
    formulas: list[str] = []
    for eid in block.element_ids:
        elem = elements_by_id.get(eid)
        if elem is None:
            continue
        if elem.type in ("text", "formula"):
            for match in LATEX_PATTERN.finditer(elem.text):
                formula = _normalize_whitespace(match.group(1))
                if formula:
                    formulas.append(formula)
    if not formulas:
        return ""
    formulas.sort()
    return _short_hash(" | ".join(formulas))


def compute_asset_signature(
    block: LayoutOwnershipBlock,
    elements_by_id: dict[str, _Element],
) -> str:
    sigs: list[str] = []
    for asset in block.assets:
        elem = elements_by_id.get(asset.asset_id)
        if elem is None:
            continue
        bbox = elem.bbox
        bbox_rounded = tuple(round(v, 2) for v in bbox)
        sigs.append(f"{elem.type}:p{elem.page}:{bbox_rounded}")
    if not sigs:
        return ""
    sigs.sort()
    return _short_hash(" | ".join(sigs))


def fingerprint_blocks(
    paper_id: str,
    blocks: list[LayoutOwnershipBlock],
    elements_by_id: dict[str, _Element],
) -> list[QuestionIdentity]:
    identities: list[QuestionIdentity] = []
    for block in blocks:
        identities.append(
            QuestionIdentity(
                block_id=block.question_block_id,
                source_position_key=build_source_position_key(
                    paper_id, block.section_path, block.question_number
                ),
                text_fingerprint=compute_text_fingerprint(block, elements_by_id),
                latex_fingerprint=compute_latex_fingerprint(block, elements_by_id),
                asset_signature=compute_asset_signature(block, elements_by_id),
            )
        )
    return identities
