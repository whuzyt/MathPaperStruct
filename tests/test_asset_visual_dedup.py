from __future__ import annotations

import unittest

from question_bank.services.asset_visual_dedup import (
    VisualAssetCandidateGroup,
    generate_visual_asset_candidates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ra(
    ra_id: str,
    paper_id: str = "paper_01",
    asset_type: str = "image",
    perceptual_hash: str = "",
) -> dict:
    return {
        "id": ra_id,
        "paper_id": paper_id,
        "asset_type": asset_type,
        "perceptual_hash": perceptual_hash,
        "content_hash": f"ch_{ra_id}",
        "crop_path": f"/tmp/{ra_id}.png",
    }


# ---------------------------------------------------------------------------
# TestVisualCandidates
# ---------------------------------------------------------------------------


class TestVisualCandidates(unittest.TestCase):
    def test_similar_hashes_within_threshold_grouped(self):
        # Two images from different papers with very similar hashes
        assets = [
            _ra("ra_1", paper_id="p1", perceptual_hash="000000000000000f"),
            _ra("ra_2", paper_id="p2", perceptual_hash="000000000000000e"),
        ]
        candidates = generate_visual_asset_candidates(assets, max_distance=8)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(len(candidates[0].members), 2)
        self.assertEqual(candidates[0].asset_type, "image")

    def test_different_hashes_not_grouped(self):
        assets = [
            _ra("ra_1", paper_id="p1", perceptual_hash="0000000000000000"),
            _ra("ra_2", paper_id="p2", perceptual_hash="ffffffffffffffff"),
        ]
        candidates = generate_visual_asset_candidates(assets, max_distance=8)
        self.assertEqual(len(candidates), 0)

    def test_different_asset_types_not_grouped(self):
        assets = [
            _ra("ra_1", paper_id="p1", asset_type="image", perceptual_hash="000000000000000f"),
            _ra("ra_2", paper_id="p2", asset_type="table", perceptual_hash="000000000000000e"),
        ]
        candidates = generate_visual_asset_candidates(assets, max_distance=8)
        self.assertEqual(len(candidates), 0)

    def test_same_paper_not_grouped(self):
        assets = [
            _ra("ra_1", paper_id="p1", perceptual_hash="000000000000000f"),
            _ra("ra_2", paper_id="p1", perceptual_hash="000000000000000e"),
        ]
        candidates = generate_visual_asset_candidates(assets, max_distance=8)
        self.assertEqual(len(candidates), 0)

    def test_empty_perceptual_hash_skipped(self):
        assets = [
            _ra("ra_1", paper_id="p1", perceptual_hash=""),
            _ra("ra_2", paper_id="p2", perceptual_hash="0000000000000000"),
        ]
        candidates = generate_visual_asset_candidates(assets, max_distance=64)
        # Only ra_2 has a pHash, ra_1 skipped → no pair possible
        self.assertEqual(len(candidates), 0)

    def test_asset_in_at_most_one_group(self):
        # ra_2 is close to both ra_1 and ra_3 — but should only join one group
        assets = [
            _ra("ra_1", paper_id="p1", perceptual_hash="0000000000000000"),
            _ra("ra_2", paper_id="p2", perceptual_hash="0000000000000002"),
            _ra("ra_3", paper_id="p3", perceptual_hash="0000000000000004"),
        ]
        candidates = generate_visual_asset_candidates(assets, max_distance=8)
        # ra_2 connects ra_1(d=1) and ra_3(d=1) → all 3 end up in one group
        # because ra_1+ra_2 pair is processed first
        total_members = sum(len(c.members) for c in candidates)
        # Each asset appears at most once across all groups
        all_ids = []
        for c in candidates:
            for m in c.members:
                all_ids.append(m["id"])
        self.assertEqual(len(all_ids), len(set(all_ids)),
                         "Each asset should appear at most once")

    def test_groups_sorted_by_size_descending(self):
        assets = [
            _ra("ra_a1", paper_id="pa", perceptual_hash="0000000000000000"),
            _ra("ra_a2", paper_id="pb", perceptual_hash="0000000000000001"),
            _ra("ra_a3", paper_id="pc", perceptual_hash="0000000000000002"),
            _ra("ra_b1", paper_id="px", perceptual_hash="aaaaaaaaaaaaaaa0"),
            _ra("ra_b2", paper_id="py", perceptual_hash="aaaaaaaaaaaaaaa1"),
        ]
        candidates = generate_visual_asset_candidates(assets, max_distance=8)
        self.assertGreaterEqual(len(candidates), 2)
        self.assertGreaterEqual(len(candidates[0].members), len(candidates[1].members))

    def test_min_candidates_filter(self):
        assets = [
            _ra("ra_1", paper_id="p1", perceptual_hash="000000000000000f"),
            _ra("ra_2", paper_id="p2", perceptual_hash="000000000000000e"),
            _ra("ra_3", paper_id="p3", perceptual_hash="000000000000000d"),
        ]
        c2 = generate_visual_asset_candidates(assets, max_distance=8, min_candidates=2)
        self.assertEqual(len(c2), 1)
        c3 = generate_visual_asset_candidates(assets, max_distance=8, min_candidates=3)
        self.assertEqual(len(c3), 1)
        c4 = generate_visual_asset_candidates(assets, max_distance=8, min_candidates=4)
        self.assertEqual(len(c4), 0)

    def test_max_distance_threshold_respected(self):
        # Only the close pair should group; the distant one excluded
        assets = [
            _ra("ra_1", paper_id="p1", perceptual_hash="0000000000000000"),
            _ra("ra_2", paper_id="p2", perceptual_hash="0000000000000003"),
            _ra("ra_3", paper_id="p3", perceptual_hash="ffffffffffffffff"),
        ]
        # max_distance=4: ra_1+ra_2 grouped (d=2), ra_3 excluded
        candidates = generate_visual_asset_candidates(assets, max_distance=4)
        self.assertEqual(len(candidates), 1)
        member_ids = [m["id"] for m in candidates[0].members]
        self.assertIn("ra_1", member_ids)
        self.assertIn("ra_2", member_ids)
        self.assertNotIn("ra_3", member_ids)

    def test_empty_input_returns_empty(self):
        self.assertEqual(generate_visual_asset_candidates([]), [])

    def test_group_structure_complete(self):
        assets = [
            _ra("ra_1", paper_id="p1", perceptual_hash="0000000000000000"),
            _ra("ra_2", paper_id="p2", perceptual_hash="0000000000000002"),
        ]
        candidates = generate_visual_asset_candidates(assets, max_distance=8)
        self.assertEqual(len(candidates), 1)
        g = candidates[0]
        self.assertTrue(g.group_id.startswith("vag_"))
        self.assertEqual(g.asset_type, "image")
        self.assertEqual(len(g.members), 2)
        self.assertGreaterEqual(g.avg_distance, 0)
        self.assertLessEqual(g.min_distance, g.max_distance)


if __name__ == "__main__":
    unittest.main()
