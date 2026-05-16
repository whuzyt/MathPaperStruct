from __future__ import annotations

import unittest

from question_bank.services.question_identity import (
    QuestionIdentity,
    build_source_position_key,
    compute_asset_signature,
    compute_latex_fingerprint,
    compute_text_fingerprint,
    fingerprint_blocks,
)
from question_bank.services.layout_ownership import (
    AssetAssignment,
    LayoutOwnershipBlock,
    _Element,
)


class TestSourcePositionKey(unittest.TestCase):
    def test_flat_section_path(self):
        key = build_source_position_key("paper_01", ("一、选择题",), "3")
        self.assertEqual(key, "paper_01#一、选择题#3")

    def test_nested_section_path(self):
        key = build_source_position_key(
            "paper_01", ("向量小题A", "一、选择题"), "2"
        )
        self.assertEqual(key, "paper_01#向量小题A/一、选择题#2")

    def test_empty_section_path(self):
        key = build_source_position_key("paper_01", (), "5")
        self.assertEqual(key, "paper_01##5")

    def test_different_papers_different_key(self):
        a = build_source_position_key("paper_A", ("一、选择题",), "1")
        b = build_source_position_key("paper_B", ("一、选择题",), "1")
        self.assertNotEqual(a, b)


class TestTextFingerprint(unittest.TestCase):
    def _elements_by_id(self, *elements: _Element) -> dict[str, _Element]:
        return {e.id: e for e in elements}

    def _block(self, element_ids: list[str], **kw) -> LayoutOwnershipBlock:
        return LayoutOwnershipBlock(
            question_block_id="qb_001",
            question_number="1",
            section_title="一、选择题",
            pages=[1],
            column_index=0,
            text_bbox=[0.0, 0.0, 1.0, 1.0],
            question_bbox=[0.0, 0.0, 1.0, 1.0],
            element_ids=element_ids,
            assets=kw.get("assets", []),
            warnings=kw.get("warnings", []),
            section_path=kw.get("section_path", ("一、选择题",)),
        )

    def _make_text(self, eid: str, text: str) -> _Element:
        return _Element(
            id=eid,
            page=1,
            type="text",
            bbox=(0.0, 0.0, 1.0, 1.0),
            text=text,
            confidence=0.98,
        )

    def test_identical_content_same_fingerprint(self):
        elements = self._elements_by_id(
            self._make_text("t1", "已知 $x=1$，求 $x+1$。"),
        )
        block_a = self._block(["t1"])
        block_b = self._block(["t1"])
        self.assertEqual(
            compute_text_fingerprint(block_a, elements),
            compute_text_fingerprint(block_b, elements),
        )

    def test_different_content_different_fingerprint(self):
        elements = self._elements_by_id(
            self._make_text("t1", "已知 $x=1$，求 $x+1$。"),
            self._make_text("t2", "计算 $2^3$ 的值。"),
        )
        fp1 = compute_text_fingerprint(self._block(["t1"]), elements)
        fp2 = compute_text_fingerprint(self._block(["t2"]), elements)
        self.assertNotEqual(fp1, fp2)

    def test_whitespace_variation_same_fingerprint(self):
        elements_a = self._elements_by_id(
            self._make_text("t1", "  已知  $x=1$  ，  求 $x+1$。  "),
        )
        elements_b = self._elements_by_id(
            self._make_text("t1", "已知 $x=1$，求 $x+1$。"),
        )
        fp1 = compute_text_fingerprint(self._block(["t1"]), elements_a)
        fp2 = compute_text_fingerprint(self._block(["t1"]), elements_b)
        self.assertEqual(fp1, fp2)

    def test_multiple_elements_concatenated(self):
        elements = self._elements_by_id(
            self._make_text("t1", "下列计算正确的是"),
            self._make_text("t2", "A. $1+1=3$"),
        )
        fp = compute_text_fingerprint(self._block(["t1", "t2"]), elements)
        self.assertTrue(len(fp) > 0)
        self.assertEqual(len(fp), 16)

    def test_empty_block_returns_empty(self):
        elements: dict[str, _Element] = {}
        fp = compute_text_fingerprint(self._block([]), elements)
        self.assertEqual(fp, "")

    def test_ignores_image_elements(self):
        elements = self._elements_by_id(
            _Element(
                id="img1",
                page=1,
                type="image",
                bbox=(0.0, 0.0, 0.5, 0.5),
                text="",
                confidence=0.98,
            ),
        )
        fp = compute_text_fingerprint(self._block(["img1"]), elements)
        self.assertEqual(fp, "")


class TestLatexFingerprint(unittest.TestCase):
    def _elements_by_id(self, *elements: _Element) -> dict[str, _Element]:
        return {e.id: e for e in elements}

    def _block(self, element_ids: list[str]) -> LayoutOwnershipBlock:
        return LayoutOwnershipBlock(
            question_block_id="qb_001",
            question_number="1",
            section_title="一、选择题",
            pages=[1],
            column_index=0,
            text_bbox=[0.0, 0.0, 1.0, 1.0],
            question_bbox=[0.0, 0.0, 1.0, 1.0],
            element_ids=element_ids,
            assets=[],
            warnings=[],
            section_path=("一、选择题",),
        )

    def _make_text(self, eid: str, text: str) -> _Element:
        return _Element(
            id=eid,
            page=1,
            type="text",
            bbox=(0.0, 0.0, 1.0, 1.0),
            text=text,
            confidence=0.98,
        )

    def test_extracts_latex_from_text(self):
        elements = self._elements_by_id(
            self._make_text("t1", "已知 $x=1$，求 $y=2$。"),
        )
        fp = compute_latex_fingerprint(self._block(["t1"]), elements)
        self.assertTrue(len(fp) > 0)
        self.assertEqual(len(fp), 16)

    def test_order_independent(self):
        elements_a = self._elements_by_id(
            self._make_text("t1", "已知 $a=1$ 和 $b=2$。"),
        )
        elements_b = self._elements_by_id(
            self._make_text("t1", "已知 $b=2$ 和 $a=1$。"),
        )
        fp1 = compute_latex_fingerprint(self._block(["t1"]), elements_a)
        fp2 = compute_latex_fingerprint(self._block(["t1"]), elements_b)
        self.assertEqual(fp1, fp2)

    def test_whitespace_in_formula_normalized(self):
        elements_a = self._elements_by_id(
            self._make_text("t1", "已知 $a  =  1$。"),
        )
        elements_b = self._elements_by_id(
            self._make_text("t1", "已知 $a=1$。"),
        )
        fp1 = compute_latex_fingerprint(self._block(["t1"]), elements_a)
        fp2 = compute_latex_fingerprint(self._block(["t1"]), elements_b)
        self.assertEqual(fp1, fp2)

    def test_no_latex_returns_empty(self):
        elements = self._elements_by_id(
            self._make_text("t1", "这是一个没有公式的问题。"),
        )
        fp = compute_latex_fingerprint(self._block(["t1"]), elements)
        self.assertEqual(fp, "")

    def test_same_formulas_different_surrounding_text_same_fingerprint(self):
        elements_a = self._elements_by_id(
            self._make_text("t1", "已知 $x^2+y^2=1$，求最值。"),
        )
        elements_b = self._elements_by_id(
            self._make_text("t2", "对于 $x^2+y^2=1$，计算范围。"),
        )
        fp1 = compute_latex_fingerprint(self._block(["t1"]), elements_a)
        fp2 = compute_latex_fingerprint(self._block(["t2"]), elements_b)
        self.assertEqual(fp1, fp2)


class TestAssetSignature(unittest.TestCase):
    def _elements_by_id(self, *elements: _Element) -> dict[str, _Element]:
        return {e.id: e for e in elements}

    def _block_with_assets(self, assets: list[AssetAssignment]) -> LayoutOwnershipBlock:
        return LayoutOwnershipBlock(
            question_block_id="qb_001",
            question_number="1",
            section_title="一、解答题",
            pages=[1],
            column_index=0,
            text_bbox=[0.0, 0.0, 1.0, 1.0],
            question_bbox=[0.0, 0.0, 1.0, 1.0],
            element_ids=["t1"],
            assets=assets,
            warnings=[],
            section_path=("三、解答题",),
        )

    def test_no_assets_returns_empty(self):
        sig = compute_asset_signature(self._block_with_assets([]), {})
        self.assertEqual(sig, "")

    def test_single_asset_signature(self):
        elements = self._elements_by_id(
            _Element(
                id="img1",
                page=2,
                type="image",
                bbox=(0.1, 0.2, 0.5, 0.6),
                text="",
                confidence=0.98,
            ),
        )
        asset = AssetAssignment(
            asset_id="img1", score=0.8, reasons=["nearby"], needs_review=False
        )
        sig = compute_asset_signature(
            self._block_with_assets([asset]), elements
        )
        self.assertTrue(len(sig) > 0)
        self.assertEqual(len(sig), 16)

    def test_same_assets_same_signature(self):
        elements = self._elements_by_id(
            _Element(
                id="img1",
                page=1,
                type="image",
                bbox=(0.1, 0.2, 0.5, 0.6),
                text="",
                confidence=0.98,
            ),
        )
        asset = AssetAssignment(
            asset_id="img1", score=0.8, reasons=["nearby"], needs_review=False
        )
        sig1 = compute_asset_signature(
            self._block_with_assets([asset]), elements
        )
        sig2 = compute_asset_signature(
            self._block_with_assets([asset]), elements
        )
        self.assertEqual(sig1, sig2)

    def test_different_positions_different_signature(self):
        elements1 = self._elements_by_id(
            _Element(
                id="img1",
                page=1,
                type="image",
                bbox=(0.1, 0.2, 0.5, 0.6),
                text="",
                confidence=0.98,
            ),
        )
        elements2 = self._elements_by_id(
            _Element(
                id="img1",
                page=1,
                type="image",
                bbox=(0.6, 0.7, 0.9, 0.95),
                text="",
                confidence=0.98,
            ),
        )
        asset = AssetAssignment(
            asset_id="img1", score=0.8, reasons=["nearby"], needs_review=False
        )
        sig1 = compute_asset_signature(
            self._block_with_assets([asset]), elements1
        )
        sig2 = compute_asset_signature(
            self._block_with_assets([asset]), elements2
        )
        self.assertNotEqual(sig1, sig2)

    def test_multiple_assets_order_independent(self):
        elements = self._elements_by_id(
            _Element(
                id="img1",
                page=1,
                type="image",
                bbox=(0.1, 0.2, 0.5, 0.6),
                text="",
                confidence=0.98,
            ),
            _Element(
                id="fig2",
                page=1,
                type="figure",
                bbox=(0.6, 0.2, 0.9, 0.5),
                text="",
                confidence=0.98,
            ),
        )
        assets_a = [
            AssetAssignment(asset_id="img1", score=0.8, reasons=["nearby"], needs_review=False),
            AssetAssignment(asset_id="fig2", score=0.7, reasons=["nearby"], needs_review=False),
        ]
        assets_b = [
            AssetAssignment(asset_id="fig2", score=0.7, reasons=["nearby"], needs_review=False),
            AssetAssignment(asset_id="img1", score=0.8, reasons=["nearby"], needs_review=False),
        ]
        sig1 = compute_asset_signature(
            self._block_with_assets(assets_a), elements
        )
        sig2 = compute_asset_signature(
            self._block_with_assets(assets_b), elements
        )
        self.assertEqual(sig1, sig2)


class TestCrossPaperIdentity(unittest.TestCase):
    def _elements_by_id(self, *elements: _Element) -> dict[str, _Element]:
        return {e.id: e for e in elements}

    def _make_text(self, eid: str, text: str) -> _Element:
        return _Element(
            id=eid,
            page=1,
            type="text",
            bbox=(0.0, 0.0, 1.0, 1.0),
            text=text,
            confidence=0.98,
        )

    def _make_block(
        self, block_id: str, qn: str, section_path: tuple[str, ...], element_ids: list[str]
    ) -> LayoutOwnershipBlock:
        return LayoutOwnershipBlock(
            question_block_id=block_id,
            question_number=qn,
            section_title=section_path[-1] if section_path else "",
            pages=[1],
            column_index=0,
            text_bbox=[0.0, 0.0, 1.0, 1.0],
            question_bbox=[0.0, 0.0, 1.0, 1.0],
            element_ids=element_ids,
            assets=[],
            warnings=[],
            section_path=section_path,
        )

    def test_same_text_different_papers_different_source_key_same_text_fp(self):
        elements = self._elements_by_id(
            self._make_text("t1", "已知 $x=1$，求 $x+2$。"),
        )
        block_a = self._make_block("qb_A", "1", ("一、选择题",), ["t1"])
        block_b = self._make_block("qb_B", "5", ("二、填空题",), ["t1"])

        ids_a = fingerprint_blocks("paper_A", [block_a], elements)
        ids_b = fingerprint_blocks("paper_B", [block_b], elements)

        self.assertNotEqual(
            ids_a[0].source_position_key, ids_b[0].source_position_key
        )
        self.assertEqual(
            ids_a[0].text_fingerprint, ids_b[0].text_fingerprint
        )

    def test_empty_block_has_empty_fingerprints(self):
        elements: dict[str, _Element] = {}
        block = self._make_block("qb_E", "1", ("一、选择题",), [])
        ids = fingerprint_blocks("paper_X", [block], elements)
        self.assertEqual(ids[0].text_fingerprint, "")
        self.assertEqual(ids[0].latex_fingerprint, "")
        self.assertEqual(ids[0].asset_signature, "")
        self.assertNotEqual(ids[0].source_position_key, "")


if __name__ == "__main__":
    unittest.main()
