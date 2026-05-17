"""ADR 004: Duplicate Review Queue v1 — Candidate group generator.

Read-only exporter that turns ADR 003 fingerprint collisions into
human-reviewable duplicate candidate groups with pairwise similarity scores.
Does NOT modify the main pipeline or existing tables.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from question_bank.services.question_identity import QuestionIdentity


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DuplicateCandidateItem:
    block_id: str
    paper_id: str
    section_path: str
    question_number: str
    source_position_key: str
    text_fingerprint: str
    latex_fingerprint: str
    asset_signature: str
    question_id: str | None = None


@dataclass(slots=True)
class SimilarityScores:
    text_match: float
    latex_match: float
    asset_match: float
    section_jaccard: float
    composite: float


@dataclass(slots=True)
class DuplicateCandidateGroup:
    id: str
    fingerprint: str
    fingerprint_type: str
    items: list[DuplicateCandidateItem]
    pairwise_similarities: dict[tuple[int, int], SimilarityScores] = field(default_factory=dict)
    status: str = "pending"


@dataclass(slots=True)
class ReviewDecision:
    group_id: str
    decision: str
    canonical_question_id: str | None
    reviewer: str
    reason: str


# ---------------------------------------------------------------------------
# Fingerprint selection
# ---------------------------------------------------------------------------


def _select_fingerprint(identity: QuestionIdentity, fp_type: str) -> str:
    if fp_type == "text":
        return identity.text_fingerprint
    if fp_type == "latex":
        return identity.latex_fingerprint
    if fp_type == "asset":
        return identity.asset_signature
    return ""


# ---------------------------------------------------------------------------
# Pairwise similarity
# ---------------------------------------------------------------------------


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


def _compute_pairwise_similarity(
    items: list[DuplicateCandidateItem],
) -> dict[tuple[int, int], SimilarityScores]:
    scores: dict[tuple[int, int], SimilarityScores] = {}
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a = items[i]
            b = items[j]

            text_match = 1.0 if (
                a.text_fingerprint and b.text_fingerprint
                and a.text_fingerprint == b.text_fingerprint
            ) else 0.0

            latex_match = 1.0 if (
                a.latex_fingerprint and b.latex_fingerprint
                and a.latex_fingerprint == b.latex_fingerprint
            ) else 0.0

            asset_match = 1.0 if (
                a.asset_signature and b.asset_signature
                and a.asset_signature == b.asset_signature
            ) else 0.0

            sj = _section_jaccard(a.section_path, b.section_path)

            composite = (
                0.25 * text_match
                + 0.35 * latex_match
                + 0.25 * asset_match
                + 0.15 * sj
            )

            scores[(i, j)] = SimilarityScores(
                text_match=text_match,
                latex_match=latex_match,
                asset_match=asset_match,
                section_jaccard=sj,
                composite=composite,
            )

    return scores


# ---------------------------------------------------------------------------
# Trimming
# ---------------------------------------------------------------------------


def _trim_top_examples(
    items: list[DuplicateCandidateItem],
    similarities: dict[tuple[int, int], SimilarityScores],
    max_items: int,
) -> list[DuplicateCandidateItem]:
    if len(items) <= max_items:
        return items

    n = len(items)
    avg_composites: list[tuple[int, float]] = []
    for i in range(n):
        total = 0.0
        count = 0
        for (a, b), s in similarities.items():
            if a == i or b == i:
                total += s.composite
                count += 1
        avg = total / count if count > 0 else 0.0
        avg_composites.append((i, avg))

    avg_composites.sort(key=lambda x: -x[1])
    kept_indices = {idx for idx, _ in avg_composites[:max_items]}
    return [item for i, item in enumerate(items) if i in kept_indices]


# ---------------------------------------------------------------------------
# Group construction
# ---------------------------------------------------------------------------


def _build_group_id(fingerprint: str) -> str:
    short = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return f"dcg_{short}"


def _build_group(
    fingerprint: str,
    items: list[DuplicateCandidateItem],
    fp_type: str,
) -> DuplicateCandidateGroup:
    similarities = _compute_pairwise_similarity(items)
    max_sim = max((s.composite for s in similarities.values()), default=0.0)

    return DuplicateCandidateGroup(
        id=_build_group_id(fingerprint),
        fingerprint=fingerprint,
        fingerprint_type=fp_type,
        items=items,
        pairwise_similarities=similarities,
        status="pending",
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_candidate_groups(
    identities_by_paper: dict[str, list[QuestionIdentity]],
    *,
    min_candidates: int = 2,
    max_items_per_group: int = 20,
    fingerprint_type: str = "text",
) -> list[DuplicateCandidateGroup]:
    fp_to_items: dict[str, list[DuplicateCandidateItem]] = {}

    for paper_id, identities in identities_by_paper.items():
        for ident in identities:
            fp = _select_fingerprint(ident, fingerprint_type)
            if not fp:
                continue
            # source_position_key = paper_id#path/components#question_number
            key = ident.source_position_key
            if "#" in key:
                body, _, qn = key.rpartition("#")
                # body = paper_id#path/components
                # Strip the leading paper_id and the trailing #
                path_str = body[len(paper_id) + 1:] if body.startswith(paper_id + "#") else ""
            else:
                qn = ""
                path_str = ""
            item = DuplicateCandidateItem(
                block_id=ident.block_id,
                paper_id=paper_id,
                section_path=path_str,
                question_number=qn,
                source_position_key=ident.source_position_key,
                text_fingerprint=ident.text_fingerprint,
                latex_fingerprint=ident.latex_fingerprint,
                asset_signature=ident.asset_signature,
            )
            fp_to_items.setdefault(fp, []).append(item)

    groups: list[DuplicateCandidateGroup] = []
    for fp, items in fp_to_items.items():
        distinct_paper_ids = {item.paper_id for item in items}
        if len(distinct_paper_ids) < min_candidates:
            continue

        trimmed = _trim_top_examples(
            items,
            _compute_pairwise_similarity(items),
            max_items_per_group,
        )
        group = _build_group(fp, trimmed, fingerprint_type)
        group.items = trimmed  # ensure items match trimmed set
        groups.append(group)

    groups.sort(key=lambda g: -len(g.items))
    return groups


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def groups_to_json(groups: list[DuplicateCandidateGroup]) -> str:
    result = []
    for g in groups:
        pairwise = {}
        for (i, j), s in g.pairwise_similarities.items():
            pairwise[f"{i},{j}"] = {
                "text_match": s.text_match,
                "latex_match": s.latex_match,
                "asset_match": s.asset_match,
                "section_jaccard": s.section_jaccard,
                "composite": s.composite,
            }
        result.append({
            "id": g.id,
            "fingerprint": g.fingerprint,
            "fingerprint_type": g.fingerprint_type,
            "status": g.status,
            "item_count": len(g.items),
            "items": [
                {
                    "block_id": item.block_id,
                    "paper_id": item.paper_id,
                    "section_path": item.section_path,
                    "question_number": item.question_number,
                    "source_position_key": item.source_position_key,
                    "text_fingerprint": item.text_fingerprint,
                    "latex_fingerprint": item.latex_fingerprint,
                    "asset_signature": item.asset_signature,
                }
                for item in g.items
            ],
            "pairwise_similarities": pairwise,
        })
    return json.dumps(result, ensure_ascii=False, indent=2)


def format_groups_summary(groups: list[DuplicateCandidateGroup]) -> str:
    if not groups:
        return "No duplicate candidate groups found."

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"  Duplicate Candidate Groups — {len(groups)} groups")
    lines.append("=" * 72)
    lines.append("")

    total_items = sum(len(g.items) for g in groups)
    lines.append(f"  Total groups : {len(groups)}")
    lines.append(f"  Total items  : {total_items}")
    lines.append("")

    lines.append(f"  {'Rank':<6} {'Group ID':<20} {'FP Type':<6} {'Items':>6} {'Max Sim':>8}  Papers")
    lines.append(f"  {'-'*6} {'-'*20} {'-'*6} {'-'*6} {'-'*8}  {'-'*20}")

    for rank, g in enumerate(groups[:50], 1):
        max_sim = max(
            (s.composite for s in g.pairwise_similarities.values()), default=0.0
        )
        papers = sorted({item.paper_id for item in g.items})
        paper_list = ", ".join(papers[:3])
        if len(papers) > 3:
            paper_list += f", ... (+{len(papers) - 3})"

        lines.append(
            f"  {rank:<6} {g.id:<20} {g.fingerprint_type:<6} "
            f"{len(g.items):>6} {max_sim:>8.3f}  {paper_list}"
        )

    lines.append("")
    lines.append("=" * 72)
    return "\n".join(lines)
