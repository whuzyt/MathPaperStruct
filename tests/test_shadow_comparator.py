import unittest

from question_bank.domain.models import QuestionBlock
from question_bank.services.layout_ownership import AssetAssignment, LayoutOwnershipBlock
from question_bank.services.shadow_comparator import compare, format_report


class ShadowComparatorTest(unittest.TestCase):
    def test_identical_questions_produce_full_match(self):
        old = [
            QuestionBlock(id="x_qb_1", paper_id="x", question_number="1", raw_markdown="1. A"),
            QuestionBlock(id="x_qb_2", paper_id="x", question_number="2", raw_markdown="2. B"),
        ]
        new = [
            LayoutOwnershipBlock(
                question_block_id="x_qb_1", question_number="1", section_title="",
                pages=[1], column_index=0, text_bbox=[0, 0, 0, 0],
                question_bbox=[0, 0, 0, 0], element_ids=["e1"], assets=[], warnings=[],
            ),
            LayoutOwnershipBlock(
                question_block_id="x_qb_2", question_number="2", section_title="",
                pages=[1], column_index=0, text_bbox=[0, 0, 0, 0],
                question_bbox=[0, 0, 0, 0], element_ids=["e2"], assets=[], warnings=[],
            ),
        ]

        report = compare("paper_001", old, new)

        self.assertEqual(report.old_question_count, 2)
        self.assertEqual(report.new_question_count, 2)
        self.assertEqual(len(report.matched_numbers), 2)
        self.assertEqual(report.old_only_numbers, [])
        self.assertEqual(report.new_only_numbers, [])

    def test_extra_questions_detected(self):
        old = [
            QuestionBlock(id="a", paper_id="x", question_number="1", raw_markdown="1. X"),
        ]
        new = [
            LayoutOwnershipBlock(
                question_block_id="a", question_number="1", section_title="",
                pages=[1], column_index=0, text_bbox=[0, 0, 0, 0],
                question_bbox=[0, 0, 0, 0], element_ids=["e1"], assets=[], warnings=[],
            ),
            LayoutOwnershipBlock(
                question_block_id="b", question_number="2", section_title="",
                pages=[1], column_index=0, text_bbox=[0, 0, 0, 0],
                question_bbox=[0, 0, 0, 0], element_ids=["e2"], assets=[], warnings=[],
            ),
        ]

        report = compare("paper_001", old, new)

        self.assertEqual(report.old_question_count, 1)
        self.assertEqual(report.new_question_count, 2)
        self.assertEqual(report.new_only_numbers, ["2"])
        self.assertEqual(report.old_only_numbers, [])

    def test_missing_questions_detected(self):
        old = [
            QuestionBlock(id="a", paper_id="x", question_number="1", raw_markdown="1. X"),
            QuestionBlock(id="b", paper_id="x", question_number="2", raw_markdown="2. Y"),
        ]
        new = [
            LayoutOwnershipBlock(
                question_block_id="a", question_number="1", section_title="",
                pages=[1], column_index=0, text_bbox=[0, 0, 0, 0],
                question_bbox=[0, 0, 0, 0], element_ids=["e1"], assets=[], warnings=[],
            ),
        ]

        report = compare("paper_001", old, new)

        self.assertEqual(report.old_question_count, 2)
        self.assertEqual(report.new_question_count, 1)
        self.assertEqual(report.old_only_numbers, ["2"])
        self.assertEqual(report.new_only_numbers, [])

    def test_warning_counts_aggregated(self):
        old = [
            QuestionBlock(id="a", paper_id="x", question_number="1", raw_markdown="1. X"),
        ]
        new = [
            LayoutOwnershipBlock(
                question_block_id="a", question_number="1", section_title="",
                pages=[1], column_index=0, text_bbox=[0, 0, 0, 0],
                question_bbox=[0, 0, 0, 0], element_ids=["e1"], assets=[],
                warnings=["orphan_formula: f1 not owned", "duplicate_question_number: 1 appears at anchor e1"],
            ),
        ]

        report = compare("paper_001", old, new)

        self.assertEqual(report.total_warnings, 2)
        self.assertEqual(report.warning_counts["orphan_formula"], 1)
        self.assertEqual(report.warning_counts["duplicate_question_number"], 1)

    def test_asset_counts_reported(self):
        old = [
            QuestionBlock(id="a", paper_id="x", question_number="1", raw_markdown="1. 如图"),
        ]
        new = [
            LayoutOwnershipBlock(
                question_block_id="a", question_number="1", section_title="",
                pages=[1], column_index=0, text_bbox=[0, 0, 0, 0],
                question_bbox=[0, 0, 0, 0], element_ids=["e1"],
                assets=[
                    AssetAssignment(asset_id="img1", score=0.85, reasons=["visual_cue"], needs_review=False),
                    AssetAssignment(asset_id="img2", score=0.50, reasons=["same_page"], needs_review=True),
                ],
                warnings=[],
            ),
        ]

        report = compare("paper_001", old, new)

        self.assertEqual(report.asset_assignment_count, 2)
        self.assertEqual(report.low_confidence_asset_count, 1)

    def test_format_report_contains_key_metrics(self):
        old = [QuestionBlock(id="a", paper_id="x", question_number="1", raw_markdown="1. X")]
        new = [
            LayoutOwnershipBlock(
                question_block_id="a", question_number="1", section_title="",
                pages=[1], column_index=0, text_bbox=[0, 0, 0, 0],
                question_bbox=[0, 0, 0, 0], element_ids=["e1"],
                assets=[], warnings=["orphan_formula: f1"],
            ),
        ]

        report = compare("paper_001", old, new)
        text = format_report(report)

        self.assertIn("paper_001", text)
        self.assertIn("old splitter question_count", text)
        self.assertIn("layout ownership question_count", text)
        self.assertIn("orphan_formula: 1", text)


if __name__ == "__main__":
    unittest.main()
