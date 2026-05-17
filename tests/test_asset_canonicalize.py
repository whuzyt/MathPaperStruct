from __future__ import annotations

import unittest

from question_bank.services.asset_canonicalize import (
    AssetVariant,
    CanonicalAsset,
    build_asset_fingerprint,
    build_canonical_asset_id,
    generate_canonical_asset_candidates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_raw_asset_dict(
    ra_id: str = "ra_abc123",
    paper_id: str = "paper_01",
    asset_type: str = "image",
    content_hash: str = "ch_abc123",
    storage_url: str | None = None,
    perceptual_hash: str = "",
) -> dict:
    return {
        "id": ra_id,
        "paper_id": paper_id,
        "asset_type": asset_type,
        "content_hash": content_hash,
        "storage_url": storage_url,
        "perceptual_hash": perceptual_hash,
    }


# ---------------------------------------------------------------------------
# TestBuildCanonicalAssetId
# ---------------------------------------------------------------------------


class TestBuildCanonicalAssetId(unittest.TestCase):
    def test_deterministic(self):
        a = build_canonical_asset_id("ch_abc123")
        b = build_canonical_asset_id("ch_abc123")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("ca_"))

    def test_different_for_different_content_hash(self):
        a = build_canonical_asset_id("ch_aaa")
        b = build_canonical_asset_id("ch_bbb")
        self.assertNotEqual(a, b)


# ---------------------------------------------------------------------------
# TestAssetFingerprint
# ---------------------------------------------------------------------------


class TestAssetFingerprint(unittest.TestCase):
    def test_stable_ordering(self):
        a = _make_raw_asset_dict(content_hash="aaa")
        b = _make_raw_asset_dict(content_hash="bbb")
        fp1 = build_asset_fingerprint([a, b])
        fp2 = build_asset_fingerprint([b, a])
        self.assertEqual(fp1, fp2)

    def test_different_content_different_fingerprint(self):
        assets_a = [_make_raw_asset_dict(content_hash="aaa")]
        assets_b = [_make_raw_asset_dict(content_hash="bbb")]
        self.assertNotEqual(
            build_asset_fingerprint(assets_a),
            build_asset_fingerprint(assets_b),
        )

    def test_empty_returns_empty(self):
        self.assertEqual(build_asset_fingerprint([]), "")

    def test_unique_content_hashes(self):
        a = _make_raw_asset_dict(content_hash="dup")
        b = _make_raw_asset_dict(content_hash="dup")
        c = _make_raw_asset_dict(content_hash="other")
        fp = build_asset_fingerprint([a, b, c])
        # Should only use unique hashes: "dup" and "other"
        self.assertTrue(len(fp) > 0)


# ---------------------------------------------------------------------------
# TestGenerateCandidates
# ---------------------------------------------------------------------------


class TestGenerateCandidates(unittest.TestCase):
    def test_same_content_hash_produces_group(self):
        raw_assets = [
            _make_raw_asset_dict(ra_id="ra_1", paper_id="paper_01", content_hash="ch_same"),
            _make_raw_asset_dict(ra_id="ra_2", paper_id="paper_02", content_hash="ch_same"),
        ]
        candidates = generate_canonical_asset_candidates(raw_assets)
        self.assertEqual(len(candidates), 1)
        self.assertIsInstance(candidates[0]["canonical"], CanonicalAsset)
        self.assertEqual(len(candidates[0]["variants"]), 2)

    def test_different_content_hash_no_group(self):
        raw_assets = [
            _make_raw_asset_dict(ra_id="ra_1", paper_id="paper_01", content_hash="ch_a"),
            _make_raw_asset_dict(ra_id="ra_2", paper_id="paper_02", content_hash="ch_b"),
        ]
        candidates = generate_canonical_asset_candidates(raw_assets)
        self.assertEqual(len(candidates), 0)

    def test_min_candidates_filter(self):
        raw_assets = [
            _make_raw_asset_dict(ra_id="ra_1", paper_id="p1", content_hash="ch_x"),
            _make_raw_asset_dict(ra_id="ra_2", paper_id="p2", content_hash="ch_x"),
            _make_raw_asset_dict(ra_id="ra_3", paper_id="p3", content_hash="ch_x"),
        ]
        result2 = generate_canonical_asset_candidates(raw_assets, min_candidates=2)
        self.assertEqual(len(result2), 1)
        result3 = generate_canonical_asset_candidates(raw_assets, min_candidates=3)
        self.assertEqual(len(result3), 1)
        result4 = generate_canonical_asset_candidates(raw_assets, min_candidates=4)
        self.assertEqual(len(result4), 0)

    def test_empty_input_returns_empty(self):
        self.assertEqual(generate_canonical_asset_candidates([]), [])

    def test_does_not_cross_asset_type(self):
        raw_assets = [
            _make_raw_asset_dict(ra_id="ra_1", paper_id="p1", asset_type="image", content_hash="ch_same"),
            _make_raw_asset_dict(ra_id="ra_2", paper_id="p2", asset_type="table", content_hash="ch_same"),
        ]
        candidates = generate_canonical_asset_candidates(raw_assets)
        self.assertEqual(len(candidates), 0)

    def test_single_paper_not_enough(self):
        raw_assets = [
            _make_raw_asset_dict(ra_id="ra_1", paper_id="paper_01", content_hash="ch_same"),
            _make_raw_asset_dict(ra_id="ra_2", paper_id="paper_01", content_hash="ch_same"),
        ]
        candidates = generate_canonical_asset_candidates(raw_assets, min_candidates=2)
        self.assertEqual(len(candidates), 0)

    def test_canonical_uses_representative_storage_url(self):
        raw_assets = [
            _make_raw_asset_dict(ra_id="ra_1", paper_id="p1", content_hash="ch_x",
                                storage_url="http://example.com/img1.png"),
            _make_raw_asset_dict(ra_id="ra_2", paper_id="p2", content_hash="ch_x"),
        ]
        candidates = generate_canonical_asset_candidates(raw_assets)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0]["canonical"].storage_url,
            "http://example.com/img1.png",
        )

    def test_variant_ids_are_deterministic(self):
        raw_assets = [
            _make_raw_asset_dict(ra_id="ra_1", paper_id="p1", content_hash="ch_x"),
            _make_raw_asset_dict(ra_id="ra_2", paper_id="p2", content_hash="ch_x"),
        ]
        c1 = generate_canonical_asset_candidates(raw_assets)
        c2 = generate_canonical_asset_candidates(raw_assets)
        self.assertEqual(
            c1[0]["variants"][0].id,
            c2[0]["variants"][0].id,
        )

    def test_multiple_groups_sorted_by_size(self):
        raw_assets = [
            _make_raw_asset_dict(ra_id="ra_1", paper_id="p1", content_hash="ch_a"),
            _make_raw_asset_dict(ra_id="ra_2", paper_id="p2", content_hash="ch_a"),
            _make_raw_asset_dict(ra_id="ra_3", paper_id="p3", content_hash="ch_a"),
            _make_raw_asset_dict(ra_id="ra_4", paper_id="p1", content_hash="ch_b"),
            _make_raw_asset_dict(ra_id="ra_5", paper_id="p2", content_hash="ch_b"),
        ]
        candidates = generate_canonical_asset_candidates(raw_assets)
        self.assertEqual(len(candidates), 2)
        # Larger group first
        self.assertEqual(len(candidates[0]["variants"]), 3)


if __name__ == "__main__":
    unittest.main()
