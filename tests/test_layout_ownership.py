import json
import unittest
from pathlib import Path

from question_bank.services.layout_ownership import (
    _has_math_feature,
    _is_instruction_number,
    layout_ownership,
)


FIXTURES_DIR = Path(__file__).resolve().parents[1] / "docs" / "test-fixtures"


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


class LayoutOwnershipFixtureTests(unittest.TestCase):
    """ADR 001 acceptance tests driven by docs/test-fixtures/*.json."""

    # ------------------------------------------------------------------
    # Fixture 1: two columns must not mix left/right questions
    # ------------------------------------------------------------------

    def test_two_column_fixture_does_not_mix_left_right_questions(self):
        fixture = _load_fixture("layout-case-two-columns.json")
        blocks = layout_ownership("paper_001", fixture["elements"])
        expected = fixture["expected"]

        self.assertEqual(
            len(blocks), expected["question_count"],
            f"expected {expected['question_count']} questions, got {len(blocks)}"
        )
        actual_numbers = [b.question_number for b in blocks]
        self.assertEqual(actual_numbers, expected["question_numbers"])
        self.assertEqual(blocks[0].column_index, 0, "question 1 should be left column")
        self.assertEqual(blocks[1].column_index, 1, "question 2 should be right column")

        # No cross-column contamination: each question's elements must stay in its column
        self.assertIn("e2", blocks[0].element_ids)
        self.assertIn("e3", blocks[0].element_ids, "option A should belong to question 1")
        self.assertIn("e4", blocks[1].element_ids)

        self.assertNotIn("e4", blocks[0].element_ids, "right-column element must not leak to left")
        self.assertNotIn("e2", blocks[1].element_ids, "left-column element must not leak to right")

    # ------------------------------------------------------------------
    # Fixture 2: image nearby with visual cue
    # ------------------------------------------------------------------

    def test_image_nearby_fixture_assigns_image_to_visual_cue_question(self):
        fixture = _load_fixture("layout-case-image-nearby.json")
        blocks = layout_ownership("paper_001", fixture["elements"])
        expected = fixture["expected"]

        self.assertEqual(len(blocks), expected["question_count"])

        # Asset assignments: img1 -> question "1"
        assign_map: dict[str, str] = {}
        for b in blocks:
            for a in b.assets:
                assign_map[a.asset_id] = b.question_number

        for asset_id, expected_q in expected["asset_assignments"].items():
            self.assertIn(asset_id, assign_map, f"{asset_id} must be assigned")
            self.assertEqual(
                assign_map[asset_id], expected_q,
                f"{asset_id} assigned to {assign_map[asset_id]}, expected {expected_q}"
            )

        # The assigned asset should have visual_cue reason
        q1 = next(b for b in blocks if b.question_number == "1")
        img_assign = next(a for a in q1.assets if a.asset_id == "img1")
        self.assertIn("visual_cue", img_assign.reasons)

    # ------------------------------------------------------------------
    # Fixture 3: cross-page continuation
    # ------------------------------------------------------------------

    def test_cross_page_fixture_merges_continuation_into_one_question(self):
        fixture = _load_fixture("layout-case-cross-page.json")
        blocks = layout_ownership("paper_001", fixture["elements"])
        expected = fixture["expected"]

        self.assertEqual(len(blocks), expected["question_count"])

        for q_num, expected_pages in expected["question_pages"].items():
            block = next(b for b in blocks if b.question_number == q_num)
            self.assertEqual(
                sorted(block.pages), sorted(expected_pages),
                f"question {q_num} pages {block.pages} != {expected_pages}"
            )

        # Question 8 should own elements from both pages
        q8 = next(b for b in blocks if b.question_number == "8")
        self.assertIn("e1", q8.element_ids, "page 1 element must belong to question 8")
        self.assertIn("e2", q8.element_ids, "page 2 continuation must belong to question 8")

        q9 = next(b for b in blocks if b.question_number == "9")
        self.assertIn("e3", q9.element_ids)
        self.assertNotIn("e2", q9.element_ids, "page 2 top element belongs to question 8, not 9")

    # ------------------------------------------------------------------
    # Fixture 4: answer section excluded
    # ------------------------------------------------------------------

    def test_answer_section_fixture_excludes_answers_from_body(self):
        fixture = _load_fixture("layout-case-answer-section.json")
        blocks = layout_ownership("paper_001", fixture["elements"])
        expected = fixture["expected"]

        self.assertEqual(len(blocks), expected["question_count"])

        all_owned: set[str] = set()
        for b in blocks:
            all_owned.update(b.element_ids)

        for excluded_id in expected["excluded_elements"]:
            self.assertNotIn(
                excluded_id, all_owned,
                f"{excluded_id} (answer section) must not appear in any question"
            )

    # ------------------------------------------------------------------
    # Fixture 5: cross-column image assignment
    # ------------------------------------------------------------------

    def test_cross_column_image_fixture_allows_full_width_figure_assignment(self):
        fixture = _load_fixture("layout-case-cross-column-image.json")
        blocks = layout_ownership("paper_001", fixture["elements"])
        expected = fixture["expected"]

        self.assertEqual(len(blocks), expected["question_count"])

        assign_map: dict[str, str] = {}
        for b in blocks:
            for a in b.assets:
                assign_map[a.asset_id] = b.question_number

        for asset_id, expected_q in expected["asset_assignments"].items():
            self.assertIn(asset_id, assign_map, f"{asset_id} must be assigned")
            self.assertEqual(assign_map[asset_id], expected_q)

        # Verify cross_column reason is present
        q1 = next(b for b in blocks if b.question_number == "1")
        img_assign = next(a for a in q1.assets if a.asset_id == "img1")
        self.assertIn("cross_column", img_assign.reasons,
                       "full-width image must use cross-column exception")

    # ------------------------------------------------------------------
    # Warning code generation
    # ------------------------------------------------------------------

    def test_duplicate_question_number_emits_warning(self):
        elements = [
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14], "text": "1. 题A"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.20, 0.50, 0.24], "text": "2. 题B"},
            {"id": "e3", "page": 1, "type": "text", "bbox": [0.08, 0.30, 0.50, 0.34], "text": "1. 题C（重复）"},
        ]
        blocks = layout_ownership("paper_001", elements)

        # All questions should still be created
        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[0].question_number, "1")
        self.assertEqual(blocks[2].question_number, "1")

    def test_low_confidence_asset_emits_warning(self):
        """Asset scoring between 0.45 and 0.62 should trigger review."""
        elements = [
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14], "text": "1. 普通题干"},
            {"id": "img1", "page": 1, "type": "image", "bbox": [0.08, 0.40, 0.50, 0.50], "text": ""},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.60, 0.50, 0.64], "text": "2. 第二题"},
        ]
        blocks = layout_ownership("paper_001", elements)

        q1 = next(b for b in blocks if b.question_number == "1")
        if q1.assets:
            self.assertTrue(q1.assets[0].needs_review)

    def test_invalid_element_bbox_is_dropped(self):
        elements = [
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14], "text": "1. 正常"},
            {"id": "bad1", "page": 1, "type": "text", "bbox": [0.5, 0.1, 0.4, 0.2], "text": "x2 <= x1"},
            {"id": "bad2", "page": 1, "type": "text", "bbox": [0.1, 0.3, 0.1, 0.4], "text": "x2 == x1"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual(len(blocks), 1)
        self.assertIn("e1", blocks[0].element_ids)
        self.assertNotIn("bad1", blocks[0].element_ids)
        self.assertNotIn("bad2", blocks[0].element_ids)

    def test_empty_elements_returns_no_blocks(self):
        blocks = layout_ownership("paper_001", [])
        self.assertEqual(len(blocks), 0)

    def test_all_elements_invalid_returns_no_blocks(self):
        elements = [
            {"id": "b1", "type": "text", "bbox": [0.5, 0.1, 0.4, 0.2], "text": "bad"},
            {"id": "b2", "page": 1, "type": "unknown_x", "bbox": [0.1, 0.1, 0.2, 0.2], "text": "bad type"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual(len(blocks), 0)

    # ------------------------------------------------------------------
    # Fixture 6: cross_column_question
    # ------------------------------------------------------------------

    def test_cross_column_question_fixture_detects_text_drift(self):
        fixture = _load_fixture("layout-case-cross-column-question.json")
        blocks = layout_ownership("paper_001", fixture["elements"])
        expected = fixture["expected"]

        self.assertEqual(len(blocks), expected["question_count"])
        actual_numbers = [b.question_number for b in blocks]
        self.assertEqual(actual_numbers, expected["question_numbers"])

        all_warnings = _collect_all_warnings(blocks)
        self.assertTrue(
            any("cross_column_question" in w for w in all_warnings),
            f"expected cross_column_question warning, got: {all_warnings}",
        )

    # ------------------------------------------------------------------
    # Fixture 7: orphan_formula
    # ------------------------------------------------------------------

    def test_orphan_formula_fixture_detects_unowned_formula(self):
        fixture = _load_fixture("layout-case-orphan-formula.json")
        blocks = layout_ownership("paper_001", fixture["elements"])
        expected = fixture["expected"]

        self.assertEqual(len(blocks), expected["question_count"])
        actual_numbers = [b.question_number for b in blocks]
        self.assertEqual(actual_numbers, expected["question_numbers"])

        all_warnings = _collect_all_warnings(blocks)
        self.assertTrue(
            any("orphan_formula" in w for w in all_warnings),
            f"expected orphan_formula warning, got: {all_warnings}",
        )
        # f_orphan must not appear in any block's element_ids
        all_owned = _collect_all_element_ids(blocks)
        self.assertNotIn("f_orphan", all_owned)

    # ------------------------------------------------------------------
    # Fixture 8: missing_anchor_suspected
    # ------------------------------------------------------------------

    def test_missing_anchor_suspected_fixture_detects_merged_question(self):
        fixture = _load_fixture("layout-case-missing-anchor-suspected.json")
        blocks = layout_ownership("paper_001", fixture["elements"])
        expected = fixture["expected"]

        self.assertEqual(len(blocks), expected["question_count"])
        actual_numbers = [b.question_number for b in blocks]
        self.assertEqual(actual_numbers, expected["question_numbers"])

        # Question "2" must NOT appear as a block (it was merged/not anchored)
        self.assertNotIn("2", actual_numbers)

        all_warnings = _collect_all_warnings(blocks)
        self.assertTrue(
            any("missing_anchor_suspected" in w for w in all_warnings),
            f"expected missing_anchor_suspected warning, got: {all_warnings}",
        )

    # ------------------------------------------------------------------
    # Fixture 9: cross_page_column_mismatch
    # ------------------------------------------------------------------

    def test_column_mismatch_fixture_detects_cross_page_layout_change(self):
        fixture = _load_fixture("layout-case-column-mismatch.json")
        blocks = layout_ownership("paper_001", fixture["elements"])
        expected = fixture["expected"]

        self.assertEqual(len(blocks), expected["question_count"])
        actual_numbers = [b.question_number for b in blocks]
        self.assertEqual(actual_numbers, expected["question_numbers"])

        # Question 2 should span pages [1, 2]
        q2 = next(b for b in blocks if b.question_number == "2")
        self.assertEqual(sorted(q2.pages), expected["question_pages"]["2"])

        all_warnings = _collect_all_warnings(blocks)
        self.assertTrue(
            any("cross_page_column_mismatch" in w for w in all_warnings),
            f"expected cross_page_column_mismatch warning, got: {all_warnings}",
        )

    # ------------------------------------------------------------------
    # Per-section duplicate scope
    # ------------------------------------------------------------------

    def test_duplicate_in_different_section_does_not_warn(self):
        """Same question number in different sections is NOT a duplicate."""
        elements = [
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.06, 0.50, 0.09], "text": "一、选择题"},
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14], "text": "1. 选择题第一题"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.18, 0.50, 0.22], "text": "2. 选择题第二题"},
            {"id": "s2", "page": 1, "type": "text", "bbox": [0.08, 0.28, 0.50, 0.31], "text": "二、填空题"},
            {"id": "e3", "page": 1, "type": "text", "bbox": [0.08, 0.34, 0.50, 0.38], "text": "1. 填空题第一题"},
            {"id": "e4", "page": 1, "type": "text", "bbox": [0.08, 0.42, 0.50, 0.46], "text": "2. 填空题第二题"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual(len(blocks), 4)
        all_warnings = _collect_all_warnings(blocks)
        duplicate_warnings = [w for w in all_warnings if "duplicate_question_number" in w]
        self.assertEqual(len(duplicate_warnings), 0,
                         f"should not flag duplicate across sections, got: {duplicate_warnings}")


    # ------------------------------------------------------------------
    # ADR 002: Nested Section Hierarchy
    # ------------------------------------------------------------------

    def test_nested_sections_do_not_flag_duplicate_across_different_paths(self):
        """ADR 002: questions with same number under different section_path
        are NOT duplicates. 向量小题A/1 and 向量小题B/1 have different paths."""
        elements = [
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.05, 0.50, 0.09], "text": "向量小题A"},
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14], "text": "1. 题目A"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.18, 0.50, 0.22], "text": "2. 题目B"},
            {"id": "s2", "page": 1, "type": "text", "bbox": [0.08, 0.28, 0.50, 0.31], "text": "向量小题B"},
            {"id": "e3", "page": 1, "type": "text", "bbox": [0.08, 0.34, 0.50, 0.38], "text": "1. 题目C"},
            {"id": "e4", "page": 1, "type": "text", "bbox": [0.08, 0.42, 0.50, 0.46], "text": "2. 题目D"},
            {"id": "s3", "page": 1, "type": "text", "bbox": [0.08, 0.52, 0.50, 0.55], "text": "向量小题C"},
            {"id": "e5", "page": 1, "type": "text", "bbox": [0.08, 0.58, 0.50, 0.62], "text": "1. 题目E"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual(len(blocks), 5)
        all_warnings = _collect_all_warnings(blocks)
        duplicate_warnings = [w for w in all_warnings if "duplicate_question_number" in w]
        self.assertEqual(len(duplicate_warnings), 0,
                         f"nested paths should prevent false duplicates, got: {duplicate_warnings}")

    def test_same_path_duplicate_still_warns(self):
        """ADR 002: same number under same section_path IS still a duplicate."""
        elements = [
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.05, 0.50, 0.09], "text": "一、选择题"},
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14], "text": "1. 题目A"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.18, 0.50, 0.22], "text": "1. 题目B（同section重复）"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual(len(blocks), 2)
        all_warnings = _collect_all_warnings(blocks)
        duplicate_warnings = [w for w in all_warnings if "duplicate_question_number" in w]
        self.assertEqual(len(duplicate_warnings), 1,
                         f"same-path duplicate must warn, got: {all_warnings}")

    def test_standard_section_nesting_with_nonstandard_top_level(self):
        """ADR 002: 专题一 → 一、选择题 nests standard under nonstandard.
        专题一/一、选择题/1 and 专题二/一、选择题/1 are different paths."""
        elements = [
            {"id": "t1", "page": 1, "type": "text", "bbox": [0.08, 0.05, 0.50, 0.09], "text": "专题一"},
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.11, 0.50, 0.15], "text": "一、选择题"},
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.17, 0.50, 0.21], "text": "1. 专题一选择题"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.25, 0.50, 0.29], "text": "2. 专题一选择题"},
            {"id": "t2", "page": 1, "type": "text", "bbox": [0.08, 0.35, 0.50, 0.39], "text": "专题二"},
            {"id": "s2", "page": 1, "type": "text", "bbox": [0.08, 0.41, 0.50, 0.45], "text": "一、选择题"},
            {"id": "e3", "page": 1, "type": "text", "bbox": [0.08, 0.47, 0.50, 0.51], "text": "1. 专题二选择题"},
            {"id": "e4", "page": 1, "type": "text", "bbox": [0.08, 0.55, 0.50, 0.59], "text": "2. 专题二选择题"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual(len(blocks), 4)
        # Verify section_path population
        q1_t1 = next(b for b in blocks if b.question_number == "1" and "专题一" in str(b.section_path))
        q1_t2 = next(b for b in blocks if b.question_number == "1" and "专题二" in str(b.section_path))
        self.assertEqual(q1_t1.section_path, ("专题一", "一、选择题"))
        self.assertEqual(q1_t2.section_path, ("专题二", "一、选择题"))
        self.assertNotEqual(q1_t1.section_path, q1_t2.section_path)
        # No duplicate warnings
        all_warnings = _collect_all_warnings(blocks)
        duplicate_warnings = [w for w in all_warnings if "duplicate_question_number" in w]
        self.assertEqual(len(duplicate_warnings), 0,
                         f"different section_paths should prevent false duplicates, got: {duplicate_warnings}")

    def test_section_path_in_output(self):
        """ADR 002: LayoutOwnershipBlock.section_path is populated correctly."""
        elements = [
            {"id": "t1", "page": 1, "type": "text", "bbox": [0.08, 0.05, 0.50, 0.09], "text": "专题一"},
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.11, 0.50, 0.15], "text": "一、选择题"},
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.17, 0.50, 0.21], "text": "1. 题目"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].section_path, ("专题一", "一、选择题"))
        self.assertEqual(blocks[0].section_title, "一、选择题")

    def test_standard_section_no_nesting(self):
        """ADR 002: standard sections stay flat when no nonstandard top-level."""
        elements = [
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.05, 0.50, 0.09], "text": "一、选择题"},
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14], "text": "1. 题目A"},
            {"id": "s2", "page": 1, "type": "text", "bbox": [0.08, 0.20, 0.50, 0.24], "text": "二、填空题"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.26, 0.50, 0.30], "text": "1. 题目B"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual(len(blocks), 2)
        q1 = next(b for b in blocks if b.question_number == "1" and b.section_title == "一、选择题")
        q1b = next(b for b in blocks if b.question_number == "1" and b.section_title == "二、填空题")
        self.assertEqual(q1.section_path, ("一、选择题",))
        self.assertEqual(q1b.section_path, ("二、填空题",))
        self.assertNotEqual(q1.section_path, q1b.section_path)
        all_warnings = _collect_all_warnings(blocks)
        duplicate_warnings = [w for w in all_warnings if "duplicate_question_number" in w]
        self.assertEqual(len(duplicate_warnings), 0)

    # ------------------------------------------------------------------
    # section_hierarchy_suspected warning (ADR 002 behavior)
    # ------------------------------------------------------------------

    def test_section_hierarchy_suspected_resolved_by_nesting(self):
        """ADR 002: section_hierarchy_suspected should NOT fire when nested
        section_paths resolve the collision. 向量小题A/B/C each have different
        paths, so the repeat question numbers are expected."""
        elements = [
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.05, 0.50, 0.09], "text": "向量小题A"},
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14], "text": "1. 题目A"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.18, 0.50, 0.22], "text": "2. 题目B"},
            {"id": "s2", "page": 1, "type": "text", "bbox": [0.08, 0.28, 0.50, 0.31], "text": "向量小题B"},
            {"id": "e3", "page": 1, "type": "text", "bbox": [0.08, 0.34, 0.50, 0.38], "text": "1. 题目C"},
            {"id": "e4", "page": 1, "type": "text", "bbox": [0.08, 0.42, 0.50, 0.46], "text": "2. 题目D"},
            {"id": "s3", "page": 1, "type": "text", "bbox": [0.08, 0.52, 0.50, 0.55], "text": "向量小题C"},
            {"id": "e5", "page": 1, "type": "text", "bbox": [0.08, 0.58, 0.50, 0.62], "text": "1. 题目E"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual(len(blocks), 5)
        all_warnings = _collect_all_warnings(blocks)
        sh_warnings = [w for w in all_warnings if "section_hierarchy_suspected" in w]
        self.assertEqual(len(sh_warnings), 0,
                         f"ADR 002 nesting should resolve SH, got: {sh_warnings}")

    def test_section_hierarchy_suspected_still_fires_on_unresolved(self):
        """ADR 002: SH still fires when same number under SAME path >= 3 times."""
        elements = [
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.05, 0.50, 0.09], "text": "向量小题A"},
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14], "text": "1. 题目A"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.18, 0.50, 0.22], "text": "1. 题目B"},
            {"id": "e3", "page": 1, "type": "text", "bbox": [0.08, 0.26, 0.50, 0.30], "text": "1. 题目C"},
        ]
        blocks = layout_ownership("paper_001", elements)
        all_warnings = _collect_all_warnings(blocks)
        sh_warnings = [w for w in all_warnings if "section_hierarchy_suspected" in w]
        self.assertEqual(len(sh_warnings), 1,
                         f"unresolved same-path duplicates should still fire SH, got: {all_warnings}")

    def test_section_hierarchy_suspected_does_not_fire_without_nonstandard_markers(self):
        """Standard sections only (一、二、) should NOT trigger the warning."""
        elements = [
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.05, 0.50, 0.09], "text": "一、选择题"},
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14], "text": "1. 题目A"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.18, 0.50, 0.22], "text": "1. 题目B（重复）"},
            {"id": "e3", "page": 1, "type": "text", "bbox": [0.08, 0.26, 0.50, 0.30], "text": "1. 题目C（重复）"},
        ]
        blocks = layout_ownership("paper_001", elements)
        all_warnings = _collect_all_warnings(blocks)
        sh_warnings = [w for w in all_warnings if "section_hierarchy_suspected" in w]
        self.assertEqual(len(sh_warnings), 0,
                         f"should not fire with standard sections only, got: {sh_warnings}")

    def test_section_hierarchy_suspected_does_not_fire_below_threshold(self):
        """Only 2 occurrences of same number — below the >= 3 threshold."""
        elements = [
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.05, 0.50, 0.09], "text": "向量小题A"},
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14], "text": "1. 题目A"},
            {"id": "s2", "page": 1, "type": "text", "bbox": [0.08, 0.28, 0.50, 0.31], "text": "向量小题B"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.34, 0.50, 0.38], "text": "1. 题目B"},
        ]
        blocks = layout_ownership("paper_001", elements)
        all_warnings = _collect_all_warnings(blocks)
        sh_warnings = [w for w in all_warnings if "section_hierarchy_suspected" in w]
        self.assertEqual(len(sh_warnings), 0,
                         f"should not fire with only 2 occurrences, got: {sh_warnings}")


class InstructionFilteringTests(unittest.TestCase):
    """ADR 012: instruction/preamble filtering in detect_question_anchors."""

    # ------------------------------------------------------------------
    # Fixture tests
    # ------------------------------------------------------------------

    def test_instruction_numbered_items_are_filtered(self):
        """Numbered instruction items before first section are filtered out."""
        fixture = _load_fixture("layout-case-instruction-number-filtered.json")
        blocks = layout_ownership("paper_001", fixture["elements"])
        expected = fixture["expected"]

        self.assertEqual(len(blocks), expected["question_count"])
        actual_numbers = [b.question_number for b in blocks]
        self.assertEqual(actual_numbers, expected["question_numbers"])

        all_warnings = _collect_all_warnings(blocks)
        self.assertTrue(
            any("instruction_number_filtered" in w for w in all_warnings),
            f"expected instruction_number_filtered warning, got: {all_warnings}",
        )

        # Real questions should own their elements
        all_owned = _collect_all_element_ids(blocks)
        self.assertIn("e3", all_owned, "real question 1 element must be owned")
        self.assertIn("e4", all_owned, "real question 2 element must be owned")
        self.assertNotIn("e1", all_owned, "instruction item 1 must not be owned")
        self.assertNotIn("e2", all_owned, "instruction item 2 must not be owned")

    def test_no_section_math_first_questions_not_filtered(self):
        """Math-first questions without any section are NOT filtered."""
        fixture = _load_fixture("layout-case-no-section-starts-with-question.json")
        blocks = layout_ownership("paper_001", fixture["elements"])
        expected = fixture["expected"]

        self.assertEqual(len(blocks), expected["question_count"])
        actual_numbers = [b.question_number for b in blocks]
        self.assertEqual(actual_numbers, expected["question_numbers"])

        all_warnings = _collect_all_warnings(blocks)
        instruction_warnings = [
            w for w in all_warnings if "instruction_number_filtered" in w
        ]
        self.assertEqual(
            len(instruction_warnings), 0,
            f"math-first questions must not be filtered, got: {instruction_warnings}",
        )

    def test_preamble_filtered_section_questions_preserved(self):
        """Preamble items filtered, section questions preserved."""
        fixture = _load_fixture("layout-case-preamble-then-section.json")
        blocks = layout_ownership("paper_001", fixture["elements"])
        expected = fixture["expected"]

        self.assertEqual(len(blocks), expected["question_count"])
        actual_numbers = [b.question_number for b in blocks]
        self.assertEqual(actual_numbers, expected["question_numbers"])

        all_warnings = _collect_all_warnings(blocks)
        self.assertTrue(
            any("instruction_number_filtered" in w for w in all_warnings),
            f"expected instruction_number_filtered warning, got: {all_warnings}",
        )

        # Section questions must be owned
        all_owned = _collect_all_element_ids(blocks)
        self.assertIn("e1", all_owned, "section question 1 must be owned")
        self.assertIn("e2", all_owned, "section question 2 must be owned")
        self.assertNotIn("e_p1", all_owned, "preamble item 1 must not be owned")
        self.assertNotIn("e_p2", all_owned, "preamble item 2 must not be owned")

    # ------------------------------------------------------------------
    # Math features override instruction cues
    # ------------------------------------------------------------------

    def test_math_features_prevent_filtering(self):
        """Instruction cue + math feature in same text → NOT filtered."""
        # "注意事项" is an instruction cue, but "已知" and "函数" are math features
        elements = [
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14],
             "text": "1. 注意事项：已知函数$f(x)=x^2$，求最小值"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.20, 0.50, 0.24],
             "text": "2. 普通题目"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual(len(blocks), 2,
                         f"math features should prevent filtering, got {len(blocks)} blocks")
        all_warnings = _collect_all_warnings(blocks)
        instruction_warnings = [
            w for w in all_warnings if "instruction_number_filtered" in w
        ]
        self.assertEqual(len(instruction_warnings), 0,
                         f"math features should prevent instruction filter, got: {instruction_warnings}")

    def test_instruction_cue_without_math_is_filtered(self):
        """Instruction cue without math feature → filtered."""
        elements = [
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14],
             "text": "1. 本试卷共4页，满分150分"},
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.22, 0.50, 0.26],
             "text": "一、选择题"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.32, 0.50, 0.36],
             "text": "1. 已知集合$A=\\{1,2,3\\}$"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual(len(blocks), 1,
                         f"instruction without math should be filtered, got {len(blocks)} blocks")
        self.assertEqual(blocks[0].question_number, "1")
        all_warnings = _collect_all_warnings(blocks)
        self.assertTrue(
            any("instruction_number_filtered" in w for w in all_warnings),
            f"expected instruction_number_filtered warning, got: {all_warnings}",
        )

    # ------------------------------------------------------------------
    # _is_instruction_number unit tests
    # ------------------------------------------------------------------

    def test_is_instruction_number_pure_instruction(self):
        self.assertTrue(_is_instruction_number(
            "1. 本试卷满分150分", "本试卷满分150分"
        ))

    def test_is_instruction_number_with_math_feature(self):
        self.assertFalse(_is_instruction_number(
            "1. 已知函数f(x)=x^2", "已知函数f(x)=x^2"
        ))

    def test_is_instruction_number_no_cue(self):
        self.assertFalse(_is_instruction_number(
            "1. 普通题目不含关键词", "普通题目不含关键词"
        ))

    def test_is_instruction_number_math_override_cue(self):
        """Math features override instruction cues."""
        self.assertFalse(_is_instruction_number(
            "1. 注意事项：已知椭圆方程求解", "注意事项：已知椭圆方程求解"
        ))

    def test_is_instruction_number_empty_text(self):
        self.assertFalse(_is_instruction_number("", ""))

    def test_is_instruction_number_dollar_sign_is_math_feature(self):
        """$ is a math feature that prevents filtering."""
        self.assertFalse(_is_instruction_number(
            "1. 本试卷含公式$f(x)$", "本试卷含公式$f(x)$"
        ))

    def test_instruction_requirements_do_not_trigger_math_feature(self):
        """'要求' in instruction prose must not count as math '求'."""
        self.assertFalse(_has_math_feature(
            "不按以上要求作答的答案无效"
        ))
        self.assertTrue(_is_instruction_number(
            "1．答题前填写姓名，不按以上要求作答的答案无效",
            "答题前填写姓名，不按以上要求作答的答案无效",
        ))

    def test_no_section_instruction_like_text_not_filtered(self):
        """Without a formal section boundary, ADR 012 filter stays inactive."""
        elements = [
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14],
             "text": "1. 本题满分10分，求答案"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.20, 0.50, 0.24],
             "text": "2. 本题满分12分，求答案"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual([b.question_number for b in blocks], ["1", "2"])
        all_warnings = _collect_all_warnings(blocks)
        self.assertFalse(any("instruction_number_filtered" in w for w in all_warnings))

    # ------------------------------------------------------------------
    # Warning code presence
    # ------------------------------------------------------------------

    def test_instruction_number_filtered_warning_in_blocks(self):
        """instruction_number_filtered warning appears in block warnings."""
        elements = [
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.10, 0.50, 0.14],
             "text": "1. 答题前请填写姓名"},
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.22, 0.50, 0.26],
             "text": "一、选择题"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.32, 0.50, 0.36],
             "text": "1. 已知$x>0$，求最小值"},
        ]
        blocks = layout_ownership("paper_001", elements)
        all_warnings = _collect_all_warnings(blocks)
        filtered_warnings = [
            w for w in all_warnings if "instruction_number_filtered" in w
        ]
        self.assertEqual(len(filtered_warnings), 1,
                         f"expected 1 instruction_number_filtered, got: {filtered_warnings}")
        self.assertIn("1 at e1", filtered_warnings[0])

    # ------------------------------------------------------------------
    # paper_0086 scenario: 23 → 22 correction
    # ------------------------------------------------------------------

    def test_instruction_filtered_does_not_create_question_block(self):
        """Filtered instruction items create NO question blocks."""
        elements = [
            {"id": "e_inst1", "page": 1, "type": "text", "bbox": [0.08, 0.06, 0.50, 0.10],
             "text": "1. 注意事项：本试卷满分150分"},
            {"id": "e_inst2", "page": 1, "type": "text", "bbox": [0.08, 0.14, 0.50, 0.18],
             "text": "2. 答题前填写姓名和准考证号"},
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.26, 0.50, 0.30],
             "text": "一、选择题"},
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.36, 0.50, 0.40],
             "text": "1. 已知集合$A=\\{1,2,3\\}$"},
        ]
        blocks = layout_ownership("paper_001", elements)
        # Only 1 real question, not 3
        self.assertEqual(len(blocks), 1,
                         f"only real question should remain, got {len(blocks)} blocks")
        self.assertEqual(blocks[0].question_number, "1")
        # Verify the real question owns its text
        self.assertIn("e1", blocks[0].element_ids)

    # ------------------------------------------------------------------
    # After-section real questions with instruction-like words are preserved.
    # ------------------------------------------------------------------

    def test_instruction_cues_after_section_are_not_filtered(self):
        """A real question with '满分' and math action cues must NOT be filtered."""
        elements = [
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.06, 0.50, 0.10],
             "text": "一、解答题"},
            {"id": "e1", "page": 1, "type": "text", "bbox": [0.08, 0.16, 0.50, 0.20],
             "text": "1. （本题满分10分）已知函数$f(x)$"},
            {"id": "e2", "page": 1, "type": "text", "bbox": [0.08, 0.26, 0.50, 0.30],
             "text": "2. （本题满分12分）设数列$\\{a_n\\}$"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual(len(blocks), 2,
                         f"after-section '满分' must not be filtered, got {len(blocks)} blocks")
        all_warnings = _collect_all_warnings(blocks)
        instruction_warnings = [
            w for w in all_warnings if "instruction_number_filtered" in w
        ]
        self.assertEqual(len(instruction_warnings), 0,
                         f"real math questions must not be filtered, got: {instruction_warnings}")

    def test_later_instruction_blocks_are_filtered(self):
        """ADR 017: numbered instructions before later paper parts are filtered."""
        elements = [
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.05, 0.50, 0.08],
             "text": "一、选择题"},
            {"id": "q1", "page": 1, "type": "text", "bbox": [0.08, 0.12, 0.50, 0.16],
             "text": "1. 已知集合$A=\\{1,2\\}$，求$A$的子集个数"},
            {"id": "s2", "page": 2, "type": "text", "bbox": [0.08, 0.05, 0.50, 0.08],
             "text": "二、非选择题"},
            {"id": "inst1", "page": 2, "type": "text", "bbox": [0.08, 0.12, 0.70, 0.16],
             "text": "1．用黑色墨水的钢笔或签字笔将答案写在答题卡上"},
            {"id": "inst2", "page": 2, "type": "text", "bbox": [0.08, 0.18, 0.70, 0.22],
             "text": "2．本卷共11小题，共105分"},
            {"id": "q2", "page": 2, "type": "text", "bbox": [0.08, 0.30, 0.50, 0.34],
             "text": "1. 已知函数$f(x)=x^2$，求$f(2)$"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual([b.question_number for b in blocks], ["1", "1"])
        all_owned = _collect_all_element_ids(blocks)
        self.assertNotIn("inst1", all_owned)
        self.assertNotIn("inst2", all_owned)
        all_warnings = _collect_all_warnings(blocks)
        filtered = [w for w in all_warnings if "instruction_number_filtered" in w]
        self.assertEqual(len(filtered), 2)

    def test_reference_formula_instruction_is_filtered_despite_math_symbols(self):
        """ADR 017: reference-formula instruction blocks should not be rescued by '$'."""
        elements = [
            {"id": "s1", "page": 1, "type": "text", "bbox": [0.08, 0.05, 0.50, 0.08],
             "text": "一、选择题"},
            {"id": "inst", "page": 1, "type": "text", "bbox": [0.08, 0.12, 0.80, 0.22],
             "text": "1．每小题选出答案后，用铅笔涂黑。参考公式：$P(A\\cup B)=P(A)+P(B)$"},
            {"id": "q1", "page": 1, "type": "text", "bbox": [0.08, 0.32, 0.50, 0.36],
             "text": "1. 已知事件$A$，求$P(A)$"},
        ]
        blocks = layout_ownership("paper_001", elements)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].element_ids, ["q1"])


def _collect_all_warnings(blocks) -> list[str]:
    all_warnings: list[str] = []
    for b in blocks:
        all_warnings.extend(b.warnings)
    return all_warnings


def _collect_all_element_ids(blocks) -> set[str]:
    ids: set[str] = set()
    for b in blocks:
        ids.update(b.element_ids)
    return ids


if __name__ == "__main__":
    unittest.main()
