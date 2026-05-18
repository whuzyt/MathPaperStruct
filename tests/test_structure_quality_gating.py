"""Tests for ADR 013: Structure Quality Gating."""

from __future__ import annotations

import unittest

from question_bank.domain.models import Choice, Question, QuestionBlock, QuestionAsset
from question_bank.services.quality import GatingResult, gate_question


def _choice(label: str, content: str = "x=1") -> Choice:
    return Choice(label=label, content_latex=content, sort_order=1)


def _question(**kwargs) -> Question:
    defaults = {
        "id": "paper_001_q_0001",
        "question_type": "single_choice",
        "stem_latex": "test stem",
        "choices": [_choice("A"), _choice("B")],
        "answer_latex": "A",
        "analysis_latex": "basic analysis",
    }
    defaults.update(kwargs)
    return Question(**defaults)


def _block(**kwargs) -> QuestionBlock:
    defaults = {
        "id": "paper_001_qb_1",
        "paper_id": "paper_001",
        "question_number": "1",
        "raw_markdown": "test markdown",
    }
    defaults.update(kwargs)
    return QuestionBlock(**defaults)


class GatingRulesTest(unittest.TestCase):
    """ADR 013: gating rule classification tests."""

    def test_empty_stem_is_failed(self):
        result = gate_question(_question(stem_latex=""))
        self.assertEqual(result.gate, "failed")
        self.assertIn("empty_stem", result.warning_codes)

    def test_empty_stem_whitespace_only_is_failed(self):
        result = gate_question(_question(stem_latex="   "))
        self.assertEqual(result.gate, "failed")

    def test_single_choice_zero_choices_is_warning(self):
        result = gate_question(_question(choices=[]))
        self.assertEqual(result.gate, "warning")
        self.assertIn("too_few_choices", result.warning_codes)

    def test_single_choice_one_choice_is_warning(self):
        result = gate_question(_question(choices=[_choice("A")]))
        self.assertEqual(result.gate, "warning")
        self.assertIn("too_few_choices", result.warning_codes)

    def test_single_choice_two_choices_is_pass_for_choice_count(self):
        result = gate_question(_question(choices=[_choice("A"), _choice("B")]))
        self.assertNotIn("too_few_choices", result.warning_codes)

    def test_answer_not_in_choices_is_warning(self):
        result = gate_question(_question(
            choices=[_choice("A"), _choice("B")],
            answer_latex="C",
        ))
        self.assertEqual(result.gate, "warning")
        self.assertIn("answer_not_in_choices", result.warning_codes)

    def test_answer_not_in_choices_but_no_choices_no_warning(self):
        """If there are no choices, answer_not_in_choices doesn't fire."""
        result = gate_question(_question(choices=[], answer_latex="A"))
        self.assertNotIn("answer_not_in_choices", result.warning_codes)

    def test_answer_empty_no_warning(self):
        """Empty answer should not trigger answer_not_in_choices."""
        result = gate_question(_question(answer_latex=""))
        self.assertNotIn("answer_not_in_choices", result.warning_codes)

    def test_proof_without_analysis_is_warning(self):
        result = gate_question(_question(
            question_type="proof",
            analysis_latex="",
        ))
        self.assertEqual(result.gate, "warning")
        self.assertIn("missing_analysis", result.warning_codes)

    def test_short_answer_without_analysis_is_warning(self):
        result = gate_question(_question(
            question_type="short_answer",
            analysis_latex="",
        ))
        self.assertEqual(result.gate, "warning")
        self.assertIn("missing_analysis", result.warning_codes)

    def test_single_choice_without_analysis_is_not_warning(self):
        """Single choice doesn't require analysis."""
        result = gate_question(_question(
            question_type="single_choice",
            analysis_latex="",
        ))
        self.assertNotIn("missing_analysis", result.warning_codes)

    def test_unbalanced_latex_stem_is_warning(self):
        result = gate_question(_question(stem_latex="here is $x$ and $y"))
        self.assertEqual(result.gate, "warning")
        self.assertIn("unbalanced_latex_delimiters", result.warning_codes)

    def test_unbalanced_latex_answer_is_warning(self):
        result = gate_question(_question(
            stem_latex="ok",
            answer_latex="$x^2",
        ))
        self.assertEqual(result.gate, "warning")
        self.assertIn("unbalanced_latex_delimiters", result.warning_codes)

    def test_balanced_latex_is_not_warning(self):
        result = gate_question(_question(stem_latex="$x^2 + y^2$"))
        self.assertNotIn("unbalanced_latex_delimiters", result.warning_codes)

    def test_block_assets_without_text_reference_is_warning(self):
        asset = QuestionAsset(
            id="img1", type="image", storage_url="",
            page=1, bbox=(0.1, 0.1, 0.3, 0.3),
        )
        block = _block(assets=[asset])
        result = gate_question(_question(
            stem_latex="no image reference here",
            answer_latex="A",
            analysis_latex="",
        ), block)
        self.assertEqual(result.gate, "warning")
        self.assertIn("asset_without_text_reference", result.warning_codes)

    def test_block_assets_with_image_reference_is_not_warning(self):
        asset = QuestionAsset(
            id="img1", type="image", storage_url="",
            page=1, bbox=(0.1, 0.1, 0.3, 0.3),
        )
        block = _block(assets=[asset])
        result = gate_question(_question(
            stem_latex="如图所示，已知 $x=1$",
            answer_latex="A",
        ), block)
        self.assertNotIn("asset_without_text_reference", result.warning_codes)

    def test_block_without_assets_no_reference_warning(self):
        """Block without assets should not trigger asset_without_text_reference."""
        block = _block(assets=[])
        result = gate_question(_question(), block)
        self.assertNotIn("asset_without_text_reference", result.warning_codes)

    def test_pass_question(self):
        result = gate_question(_question(
            stem_latex="已知 $x=1$，求 $x+1$ 的值",
            choices=[_choice("A"), _choice("B"), _choice("C"), _choice("D")],
            answer_latex="B",
            analysis_latex="x+1=2",
            question_type="single_choice",
        ))
        self.assertEqual(result.gate, "pass")
        self.assertEqual(result.warning_codes, [])

    def test_multiple_warnings_aggregated(self):
        """Multiple warning conditions produce all warning codes."""
        result = gate_question(_question(
            question_type="proof",
            stem_latex="test $x",
            choices=[],
            answer_latex="",
            analysis_latex="",
        ))
        self.assertEqual(result.gate, "warning")
        self.assertIn("unbalanced_latex_delimiters", result.warning_codes)
        self.assertIn("missing_analysis", result.warning_codes)

    def test_failed_trumps_warnings(self):
        """Even if there are warning conditions, empty stem → failed."""
        result = gate_question(_question(
            stem_latex="",
            question_type="proof",
            analysis_latex="",
        ))
        self.assertEqual(result.gate, "failed")
        self.assertIn("empty_stem", result.warning_codes)

    def test_gating_result_fields(self):
        result = gate_question(_question(stem_latex=""))
        self.assertEqual(result.question_id, "paper_001_q_0001")
        self.assertEqual(result.gate, "failed")
        self.assertIsInstance(result.warning_codes, list)

    def test_fill_blank_no_analysis_not_warning(self):
        """Fill-blank doesn't require analysis."""
        result = gate_question(_question(
            question_type="fill_blank",
            analysis_latex="",
        ))
        self.assertNotIn("missing_analysis", result.warning_codes)


if __name__ == "__main__":
    unittest.main()
