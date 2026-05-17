from __future__ import annotations

import unittest

from question_bank.services.asset_identity import (
    RawAsset,
    build_raw_asset_id,
    compute_content_hash,
    identify_raw_assets,
)
from question_bank.services.layout_ownership import (
    AssetAssignment,
    LayoutOwnershipBlock,
    _Element,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_element(
    eid: str = "img_001",
    page: int = 1,
    etype: str = "image",
    bbox: tuple[float, float, float, float] = (0.1, 0.2, 0.5, 0.6),
    text: str = "",
    confidence: float = 0.98,
) -> _Element:
    return _Element(
        id=eid,
        page=page,
        type=etype,
        bbox=bbox,
        text=text,
        confidence=confidence,
        width=bbox[2] - bbox[0],
        height=bbox[3] - bbox[1],
    )


def _make_block(
    block_id: str = "paper_01_qb_1",
    question_number: str = "1",
    section_path: tuple[str, ...] = ("一、选择题",),
    element_ids: list[str] | None = None,
    assets: list[AssetAssignment] | None = None,
) -> LayoutOwnershipBlock:
    return LayoutOwnershipBlock(
        question_block_id=block_id,
        question_number=question_number,
        section_title=section_path[-1] if section_path else "",
        pages=[1],
        column_index=0,
        text_bbox=[0.08, 0.12, 0.46, 0.29],
        question_bbox=[0.08, 0.12, 0.55, 0.40],
        element_ids=element_ids or [],
        assets=assets or [],
        warnings=[],
        section_path=section_path,
    )


def _make_asset_assignment(
    asset_id: str = "img_001",
    score: float = 0.8,
    reasons: list[str] | None = None,
    needs_review: bool = False,
) -> AssetAssignment:
    return AssetAssignment(
        asset_id=asset_id,
        score=score,
        reasons=reasons or ["nearby"],
        needs_review=needs_review,
    )


# ---------------------------------------------------------------------------
# TestRawAssetId
# ---------------------------------------------------------------------------


class TestRawAssetId(unittest.TestCase):
    def test_same_inputs_same_id(self):
        a = build_raw_asset_id("paper_01", 1, (0.1, 0.2, 0.5, 0.6), "image", "img_001")
        b = build_raw_asset_id("paper_01", 1, (0.1, 0.2, 0.5, 0.6), "image", "img_001")
        self.assertEqual(a, b)

    def test_different_bbox_different_id(self):
        a = build_raw_asset_id("paper_01", 1, (0.1, 0.2, 0.5, 0.6), "image", "img_001")
        b = build_raw_asset_id("paper_01", 1, (0.15, 0.25, 0.55, 0.65), "image", "img_001")
        self.assertNotEqual(a, b)

    def test_different_paper_different_id(self):
        a = build_raw_asset_id("paper_01", 1, (0.1, 0.2, 0.5, 0.6), "image", "img_001")
        b = build_raw_asset_id("paper_02", 1, (0.1, 0.2, 0.5, 0.6), "image", "img_001")
        self.assertNotEqual(a, b)

    def test_different_type_different_id(self):
        a = build_raw_asset_id("paper_01", 1, (0.1, 0.2, 0.5, 0.6), "image", "img_001")
        b = build_raw_asset_id("paper_01", 1, (0.1, 0.2, 0.5, 0.6), "table", "img_001")
        self.assertNotEqual(a, b)

    def test_bbox_rounded_to_4_decimals(self):
        a = build_raw_asset_id("paper_01", 1, (0.12345, 0.2, 0.5, 0.6), "image", "img_001")
        b = build_raw_asset_id("paper_01", 1, (0.12341, 0.2, 0.5, 0.6), "image", "img_001")
        self.assertNotEqual(a, b)  # 0.12345→0.1235 vs 0.12341→0.1234


# ---------------------------------------------------------------------------
# TestContentHash
# ---------------------------------------------------------------------------


class TestContentHash(unittest.TestCase):
    def test_same_position_same_hash(self):
        a = compute_content_hash(1, (0.1, 0.2, 0.5, 0.6), "image")
        b = compute_content_hash(1, (0.1, 0.2, 0.5, 0.6), "image")
        self.assertEqual(a, b)

    def test_different_bbox_different_hash(self):
        a = compute_content_hash(1, (0.1, 0.2, 0.5, 0.6), "image")
        b = compute_content_hash(1, (0.15, 0.25, 0.55, 0.65), "image")
        self.assertNotEqual(a, b)

    def test_different_type_different_hash(self):
        a = compute_content_hash(1, (0.1, 0.2, 0.5, 0.6), "image")
        b = compute_content_hash(1, (0.1, 0.2, 0.5, 0.6), "figure")
        self.assertNotEqual(a, b)

    def test_different_page_different_hash(self):
        a = compute_content_hash(1, (0.1, 0.2, 0.5, 0.6), "image")
        b = compute_content_hash(2, (0.1, 0.2, 0.5, 0.6), "image")
        self.assertNotEqual(a, b)


# ---------------------------------------------------------------------------
# TestIdentifyRawAssets
# ---------------------------------------------------------------------------


class TestIdentifyRawAssets(unittest.TestCase):
    def test_block_with_one_asset_returns_one_raw_asset_and_link(self):
        elements_by_id = {"img_001": _make_element("img_001")}
        block = _make_block(
            block_id="paper_01_qb_1",
            assets=[_make_asset_assignment("img_001", score=0.85)],
        )
        raw_assets, links = identify_raw_assets("paper_01", [block], elements_by_id)
        self.assertEqual(len(raw_assets), 1)
        self.assertEqual(len(links), 1)
        self.assertEqual(raw_assets[0].paper_id, "paper_01")
        self.assertEqual(raw_assets[0].asset_type, "image")
        self.assertEqual(raw_assets[0].source_element_id, "img_001")

    def test_block_with_zero_assets_returns_empty(self):
        elements_by_id = {}
        block = _make_block(block_id="paper_01_qb_1", assets=[])
        raw_assets, links = identify_raw_assets("paper_01", [block], elements_by_id)
        self.assertEqual(len(raw_assets), 0)
        self.assertEqual(len(links), 0)

    def test_block_with_two_assets_returns_two_of_each(self):
        elements_by_id = {
            "img_001": _make_element("img_001"),
            "img_002": _make_element("img_002", bbox=(0.6, 0.2, 0.9, 0.5)),
        }
        block = _make_block(
            block_id="paper_01_qb_1",
            assets=[
                _make_asset_assignment("img_001", score=0.85),
                _make_asset_assignment("img_002", score=0.72),
            ],
        )
        raw_assets, links = identify_raw_assets("paper_01", [block], elements_by_id)
        self.assertEqual(len(raw_assets), 2)
        self.assertEqual(len(links), 2)

    def test_link_includes_block_id_as_question_id(self):
        elements_by_id = {"img_001": _make_element("img_001")}
        block = _make_block(
            block_id="paper_01_qb_1",
            assets=[_make_asset_assignment("img_001")],
        )
        _, links = identify_raw_assets("paper_01", [block], elements_by_id)
        self.assertEqual(links[0]["question_id"], "paper_01_qb_1")
        self.assertIsNone(links[0]["canonical_question_id"])

    def test_link_includes_confidence_and_needs_review(self):
        elements_by_id = {"img_001": _make_element("img_001")}
        block = _make_block(
            block_id="paper_01_qb_1",
            assets=[_make_asset_assignment("img_001", score=0.55, needs_review=True)],
        )
        _, links = identify_raw_assets("paper_01", [block], elements_by_id)
        self.assertEqual(links[0]["confidence"], 0.55)
        self.assertTrue(links[0]["needs_review"])

    def test_link_id_is_deterministic(self):
        elements_by_id = {"img_001": _make_element("img_001")}
        block = _make_block(
            block_id="paper_01_qb_1",
            assets=[_make_asset_assignment("img_001")],
        )
        _, links1 = identify_raw_assets("paper_01", [block], elements_by_id)
        _, links2 = identify_raw_assets("paper_01", [block], elements_by_id)
        self.assertEqual(links1[0]["id"], links2[0]["id"])

    def test_skips_missing_element(self):
        elements_by_id: dict[str, _Element] = {}
        block = _make_block(
            block_id="paper_01_qb_1",
            assets=[_make_asset_assignment("img_missing")],
        )
        raw_assets, links = identify_raw_assets("paper_01", [block], elements_by_id)
        self.assertEqual(len(raw_assets), 0)
        self.assertEqual(len(links), 0)

    def test_perceptual_hash_is_empty(self):
        elements_by_id = {"img_001": _make_element("img_001")}
        block = _make_block(
            block_id="paper_01_qb_1",
            assets=[_make_asset_assignment("img_001")],
        )
        raw_assets, _ = identify_raw_assets("paper_01", [block], elements_by_id)
        self.assertEqual(raw_assets[0].perceptual_hash, "")

    def test_crop_path_and_storage_url_are_none(self):
        elements_by_id = {"img_001": _make_element("img_001")}
        block = _make_block(
            block_id="paper_01_qb_1",
            assets=[_make_asset_assignment("img_001")],
        )
        raw_assets, _ = identify_raw_assets("paper_01", [block], elements_by_id)
        self.assertIsNone(raw_assets[0].crop_path)
        self.assertIsNone(raw_assets[0].storage_url)

    def test_raw_asset_has_correct_dimensions(self):
        elements_by_id = {"img_001": _make_element("img_001", bbox=(0.1, 0.2, 0.5, 0.6))}
        block = _make_block(
            block_id="paper_01_qb_1",
            assets=[_make_asset_assignment("img_001")],
        )
        raw_assets, _ = identify_raw_assets("paper_01", [block], elements_by_id)
        self.assertAlmostEqual(raw_assets[0].width, 0.4, places=4)
        self.assertAlmostEqual(raw_assets[0].height, 0.4, places=4)

    def test_multiple_blocks_each_with_assets(self):
        elements_by_id = {
            "img_001": _make_element("img_001", bbox=(0.1, 0.2, 0.3, 0.4)),
            "img_002": _make_element("img_002", bbox=(0.5, 0.6, 0.7, 0.8)),
        }
        block1 = _make_block(
            block_id="paper_01_qb_1",
            assets=[_make_asset_assignment("img_001")],
        )
        block2 = _make_block(
            block_id="paper_01_qb_2",
            assets=[_make_asset_assignment("img_002")],
        )
        raw_assets, links = identify_raw_assets(
            "paper_01", [block1, block2], elements_by_id
        )
        self.assertEqual(len(raw_assets), 2)
        self.assertEqual(len(links), 2)
        self.assertEqual(raw_assets[0].source_element_id, "img_001")
        self.assertEqual(raw_assets[1].source_element_id, "img_002")


if __name__ == "__main__":
    unittest.main()
