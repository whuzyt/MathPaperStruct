"""ADR 005: Question Canonicalization v1.

Generates canonical questions from resolved duplicate groups.
Only triggered when a human marks a group as "same" via ADR 004 decisions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CanonicalQuestion:
    id: str
    canonical_fingerprint: str
    representative_item_id: str
    stem_latex: str
    answer_latex: str
    analysis_latex: str
    question_type: str
    difficulty: int | None
    status: str
    created_from_group_id: str


@dataclass(slots=True)
class QuestionVariant:
    id: str
    canonical_question_id: str
    question_id: str | None
    paper_id: str
    variant_type: str
    source_position_key: str
    text_fingerprint: str
    latex_fingerprint: str
    asset_signature: str
    is_active: bool = True


@dataclass(slots=True)
class CanonicalizationEvent:
    id: str
    canonical_question_id: str
    group_id: str
    event_type: str
    payload_json: str
    created_by: str


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def is_eligible_for_canonicalization(group: dict) -> bool:
    """Group must have at least one 'same' decision."""
    decisions = group.get("decisions", [])
    return any(d.get("decision") == "same" for d in decisions)


def build_canonical_id(group_id: str) -> str:
    return f"cqn_{_short_hash(group_id)}"


def select_representative(items: list[dict]) -> dict:
    """Select the item with highest average composite similarity to all peers.

    Tie-break: min source_position_key (lexicographic).
    """
    if len(items) <= 1:
        return items[0] if items else {}

    similarities = _compute_similarities(items)
    n = len(items)
    best_idx = 0
    best_avg = -1.0
    best_key = ""

    for i in range(n):
        total = 0.0
        count = 0
        for (a, b), composite in similarities.items():
            if a == i or b == i:
                total += composite
                count += 1
        avg = total / count if count > 0 else 0.0

        key = items[i].get("source_position_key", "")
        if avg > best_avg or (avg == best_avg and key < best_key):
            best_avg = avg
            best_idx = i
            best_key = key

    return items[best_idx]


def canonicalize_group(
    group: dict,
    created_by: str,
) -> dict:
    """Generate a canonical question from a duplicate group.

    Returns a dict with keys: canonical, variants, event.
    Caller is responsible for persisting to the database.
    """
    if not is_eligible_for_canonicalization(group):
        raise ValueError(f"Group {group.get('id', 'unknown')} has no 'same' decision")

    canonical_id = build_canonical_id(group["id"])
    items = group.get("items", [])
    if not items:
        raise ValueError(f"Group {group['id']} has no items")

    representative = select_representative(items)

    # Build canonical fingerprint from sorted unique text fingerprints
    text_fps = sorted({i.get("text_fingerprint", "") for i in items if i.get("text_fingerprint")})
    canonical_fp = _short_hash(" | ".join(text_fps)) if text_fps else ""

    canonical = CanonicalQuestion(
        id=canonical_id,
        canonical_fingerprint=canonical_fp,
        representative_item_id=representative.get("block_id", ""),
        stem_latex="",
        answer_latex="",
        analysis_latex="",
        question_type="",
        difficulty=None,
        status="active",
        created_from_group_id=group["id"],
    )

    variants: list[QuestionVariant] = []
    for item in items:
        variant = QuestionVariant(
            id=f"{canonical_id}_var_{item.get('block_id', '')}",
            canonical_question_id=canonical_id,
            question_id=item.get("question_id"),
            paper_id=item.get("paper_id", ""),
            variant_type="candidate",
            source_position_key=item.get("source_position_key", ""),
            text_fingerprint=item.get("text_fingerprint", ""),
            latex_fingerprint=item.get("latex_fingerprint", ""),
            asset_signature=item.get("asset_signature", ""),
            is_active=True,
        )
        variants.append(variant)

    event_payload = {
        "item_count": len(items),
        "representative_item_id": representative.get("block_id", ""),
        "variant_ids": [v.id for v in variants],
    }
    event = CanonicalizationEvent(
        id=f"{canonical_id}_evt_created",
        canonical_question_id=canonical_id,
        group_id=group["id"],
        event_type="created",
        payload_json=json.dumps(event_payload, ensure_ascii=False),
        created_by=created_by,
    )

    return {
        "canonical": canonical,
        "variants": variants,
        "event": event,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _section_jaccard(path_a: str, path_b: str) -> float:
    comps_a = set(filter(None, path_a.split("/")))
    comps_b = set(filter(None, path_b.split("/")))
    if not comps_a and not comps_b:
        return 0.0
    union = comps_a | comps_b
    if not union:
        return 0.0
    intersection = comps_a & comps_b
    return len(intersection) / len(union)


def _compute_similarities(
    items: list[dict],
) -> dict[tuple[int, int], float]:
    """Compute pairwise composite similarity for a list of item dicts."""
    scores: dict[tuple[int, int], float] = {}
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a = items[i]
            b = items[j]

            text_match = 1.0 if (
                a.get("text_fingerprint") and b.get("text_fingerprint")
                and a["text_fingerprint"] == b["text_fingerprint"]
            ) else 0.0

            latex_match = 1.0 if (
                a.get("latex_fingerprint") and b.get("latex_fingerprint")
                and a["latex_fingerprint"] == b["latex_fingerprint"]
            ) else 0.0

            asset_match = 1.0 if (
                a.get("asset_signature") and b.get("asset_signature")
                and a["asset_signature"] == b["asset_signature"]
            ) else 0.0

            sj = _section_jaccard(
                a.get("section_path", ""), b.get("section_path", "")
            )

            composite = (
                0.25 * text_match
                + 0.35 * latex_match
                + 0.25 * asset_match
                + 0.15 * sj
            )

            scores[(i, j)] = composite

    return scores
