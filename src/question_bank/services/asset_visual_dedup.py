"""ADR 008: Asset Visual Dedup v1 — Group raw_assets by perceptual hash similarity.

Candidate discovery only — never auto-merge. Uses hamming distance on
perceptual hashes to find visually similar assets across papers.

Constraints:
- Never cross asset_type
- Require ≥2 distinct papers per group
- Each raw_asset in at most one group (greedy: smallest distance first)
"""

from __future__ import annotations

from dataclasses import dataclass

from question_bank.services.image_phash import hamming_distance


@dataclass(slots=True)
class VisualAssetCandidateGroup:
    group_id: str
    asset_type: str
    members: list[dict]
    avg_distance: float
    min_distance: int
    max_distance: int


def generate_visual_asset_candidates(
    raw_assets: list[dict],
    max_distance: int = 8,
    min_candidates: int = 2,
) -> list[VisualAssetCandidateGroup]:
    # 1. Filter to assets with non-empty perceptual_hash
    eligible = [
        ra for ra in raw_assets
        if ra.get("perceptual_hash", "") and ra.get("paper_id", "")
    ]

    if not eligible:
        return []

    # 2. Build all valid pairs (same asset_type, different papers, within distance)
    edges: list[tuple[int, str, str, str]] = []  # (distance, ra_id_a, ra_id_b, asset_type)
    for i in range(len(eligible)):
        a = eligible[i]
        for j in range(i + 1, len(eligible)):
            b = eligible[j]
            # Never cross asset_type
            if a.get("asset_type", "") != b.get("asset_type", ""):
                continue
            # Require different papers
            if a.get("paper_id", "") == b.get("paper_id", ""):
                continue

            d = hamming_distance(a["perceptual_hash"], b["perceptual_hash"])
            if d <= max_distance:
                edges.append((d, a["id"], b["id"], a.get("asset_type", "")))

    edges.sort(key=lambda e: e[0])  # smallest distance first

    # 3. Greedy clustering: each asset in at most one group
    asset_to_group: dict[str, int] = {}
    groups_members: list[list[dict]] = []
    groups_distances: list[list[int]] = []

    # Build lookup for raw_asset by id
    ra_by_id: dict[str, dict] = {ra["id"]: ra for ra in eligible}

    for d, id_a, id_b, atype in edges:
        ra_a = ra_by_id.get(id_a)
        ra_b = ra_by_id.get(id_b)
        if ra_a is None or ra_b is None:
            continue

        ga = asset_to_group.get(id_a)
        gb = asset_to_group.get(id_b)

        if ga is not None and gb is not None:
            # Both already assigned — could merge groups, but that's complex
            # Keep them separate in v1
            continue
        elif ga is not None:
            # Add b to a's group
            asset_to_group[id_b] = ga
            groups_members[ga].append(ra_b)
            groups_distances[ga].append(d)
        elif gb is not None:
            # Add a to b's group
            asset_to_group[id_a] = gb
            groups_members[gb].append(ra_a)
            groups_distances[gb].append(d)
        else:
            # Create new group
            g_idx = len(groups_members)
            asset_to_group[id_a] = g_idx
            asset_to_group[id_b] = g_idx
            groups_members.append([ra_a, ra_b])
            groups_distances.append([d])

    # 4. Filter by min_candidates (distinct papers)
    candidates: list[VisualAssetCandidateGroup] = []
    for g_idx, members in enumerate(groups_members):
        papers = {m.get("paper_id", "") for m in members}
        if len(papers) < min_candidates:
            continue

        dists = groups_distances[g_idx]
        avg_d = sum(dists) / len(dists) if dists else 0.0
        min_d = min(dists) if dists else 0
        max_d = max(dists) if dists else 0

        asset_type = members[0].get("asset_type", "")

        group_id = f"vag_{_short_hash('|'.join(sorted(p['id'] for p in members)))}"

        candidates.append(VisualAssetCandidateGroup(
            group_id=group_id,
            asset_type=asset_type,
            members=members,
            avg_distance=avg_d,
            min_distance=min_d,
            max_distance=max_d,
        ))

    # 5. Sort by size descending
    candidates.sort(key=lambda g: -len(g.members))
    return candidates


def _short_hash(content: str) -> str:
    import hashlib
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
