"""Tests for ADR 015: DeepSeek Prompt Hardening v1."""

from __future__ import annotations

import unittest

from question_bank.domain.models import Choice, Question, QuestionAsset, QuestionBlock
from question_bank.services.paper_orchestrator import _harden_question


def _choice(label: str, content: str = "x=1") -> Choice:
    return Choice(label=label, content_latex=content, sort_order=1)


def _question(**kwargs) -> Question:
    defaults = {
        "id": "paper_001_q_0001",
        "question_type": "single_choice",
        "stem_latex": "test stem",
        "choices": [_choice("A"), _choice("B"), _choice("C"), _choice("D")],
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


# ---------------------------------------------------------------------------
# TestAnswerNormalization
# ---------------------------------------------------------------------------


class TestAnswerNormalization(unittest.TestCase):
    """ADR 015: answer_latex normalization to choice label."""

    def test_full_content_answer_matched_to_label(self):
        """When answer is the full choice content, normalize to label."""
        q = _question(
            choices=[_choice("A", "$x^2 + y^2 = z^2$"), _choice("B", "$a+b=c$")],
            answer_latex="$x^2 + y^2 = z^2$",
        )
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertEqual(q.answer_latex, "A")
        self.assertTrue(any("answer_normalized" in w for w in payload.get("warnings", [])))

    def test_partial_content_answer_matched_to_label(self):
        """When answer is contained within choice content, normalize to label."""
        q = _question(
            choices=[_choice("A", "x=1, y=2"), _choice("B", "x=3")],
            answer_latex="x=1",
        )
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertEqual(q.answer_latex, "A")

    def test_single_letter_answer_preserved(self):
        """When answer is already a valid label, don't change it."""
        q = _question(answer_latex="B")
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertEqual(q.answer_latex, "B")

    def test_single_letter_lowercase_normalized(self):
        """Single lowercase letter matching a choice label should be uppercased."""
        q = _question(
            choices=[_choice("A", "x=1"), _choice("B", "x=2")],
            answer_latex="b",
        )
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertEqual(q.answer_latex, "B")

    def test_single_letter_not_in_labels_gets_normalized(self):
        """A single letter not in choice labels but A-H → uppercased."""
        q = _question(
            choices=[_choice("A", "x=1"), _choice("B", "x=2")],
            answer_latex="c",
        )
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertEqual(q.answer_latex, "C")

    def test_empty_answer_not_changed(self):
        """Empty answer should not be changed."""
        q = _question(answer_latex="")
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertEqual(q.answer_latex, "")

    def test_full_content_answer_no_match_leaves_unchanged(self):
        """When answer doesn't match any choice content, leave unchanged."""
        q = _question(
            choices=[_choice("A", "x=1"), _choice("B", "x=2")],
            answer_latex="completely different text",
        )
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertEqual(q.answer_latex, "completely different text")

    def test_answer_normalization_records_warning(self):
        """answer_normalized adds a model warning."""
        q = _question(
            choices=[_choice("A", "$x^2 + y^2 = z^2$"), _choice("B", "$a+b=c$")],
            answer_latex="$x^2 + y^2 = z^2$",
        )
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertTrue(any("answer_normalized" in w for w in payload.get("warnings", [])))


# ---------------------------------------------------------------------------
# TestChoicePadding
# ---------------------------------------------------------------------------


class TestChoicePadding(unittest.TestCase):
    """ADR 015: choice补齐 from raw_markdown when choices < 2."""

    def test_single_choice_padded_from_raw_markdown(self):
        """When single_choice has 0 choices, parse from raw_markdown."""
        q = _question(
            question_type="single_choice",
            choices=[],
        )
        block = _block(raw_markdown="A. x=1\nB. x=2\nC. x=3\nD. x=4")
        payload: dict = {}
        _harden_question(q, block, payload)
        self.assertGreaterEqual(len(q.choices), 2)

    def test_single_choice_one_choice_padded(self):
        """When single_choice has 1 choice, parse extras from raw_markdown."""
        q = _question(
            question_type="single_choice",
            choices=[_choice("A", "x=1")],
        )
        block = _block(raw_markdown="A. x=1\nB. x=2\nC. x=3\nD. x=4")
        payload: dict = {}
        _harden_question(q, block, payload)
        self.assertGreaterEqual(len(q.choices), 2)

    def test_two_choices_not_padded(self):
        """When single_choice already has 2 choices, don't add more."""
        q = _question(
            question_type="single_choice",
            choices=[_choice("A", "x=1"), _choice("B", "x=2")],
        )
        block = _block(raw_markdown="A. x=1\nB. x=2\nC. x=3\nD. x=4")
        payload: dict = {}
        _harden_question(q, block, payload)
        self.assertEqual(len(q.choices), 2)

    def test_padding_does_not_duplicate_labels(self):
        """Parsed choices with same label should not duplicate existing ones."""
        q = _question(
            question_type="single_choice",
            choices=[_choice("A", "x=1")],
        )
        block = _block(raw_markdown="A. x=1\nB. x=2")
        payload: dict = {}
        _harden_question(q, block, payload)
        labels = [c.label for c in q.choices]
        self.assertEqual(len(labels), len(set(labels)))  # no duplicates

    def test_non_single_choice_not_padded(self):
        """Proof/short_answer questions should not have choices padded."""
        q = _question(
            question_type="proof",
            choices=[],
        )
        block = _block(raw_markdown="A. x=1\nB. x=2")
        payload: dict = {}
        _harden_question(q, block, payload)
        self.assertEqual(len(q.choices), 0)


# ---------------------------------------------------------------------------
# TestAnalysisFallback
# ---------------------------------------------------------------------------


class TestAnalysisFallback(unittest.TestCase):
    """ADR 015: analysis_latex fallback for proof/short_answer."""

    def test_proof_without_analysis_gets_fallback(self):
        q = _question(
            question_type="proof",
            analysis_latex="",
        )
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertEqual(q.analysis_latex, "暂无解析，待人工补充")
        self.assertTrue(any("analysis_fallback" in w for w in payload.get("warnings", [])))

    def test_short_answer_without_analysis_gets_fallback(self):
        q = _question(
            question_type="short_answer",
            analysis_latex="",
        )
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertEqual(q.analysis_latex, "暂无解析，待人工补充")

    def test_proof_with_analysis_preserved(self):
        q = _question(
            question_type="proof",
            analysis_latex="detailed proof here",
        )
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertEqual(q.analysis_latex, "detailed proof here")

    def test_single_choice_analysis_not_fallbacked(self):
        """Single_choice doesn't need analysis fallback."""
        q = _question(
            question_type="single_choice",
            analysis_latex="",
        )
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertEqual(q.analysis_latex, "")

    def test_fill_blank_analysis_not_fallbacked(self):
        q = _question(
            question_type="fill_blank",
            analysis_latex="",
        )
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertEqual(q.analysis_latex, "")

    def test_whitespace_only_analysis_gets_fallback(self):
        q = _question(
            question_type="proof",
            analysis_latex="   ",
        )
        payload: dict = {}
        _harden_question(q, _block(), payload)
        self.assertEqual(q.analysis_latex, "暂无解析，待人工补充")


# ---------------------------------------------------------------------------
# TestImageReferenceMarker
# ---------------------------------------------------------------------------


class TestImageReferenceMarker(unittest.TestCase):
    """ADR 015: stem [图] marker for asset blocks without image reference."""

    def test_asset_block_without_reference_adds_marker(self):
        asset = QuestionAsset(
            id="img1", type="image", storage_url="",
            page=1, bbox=(0.1, 0.1, 0.3, 0.3),
        )
        block = _block(assets=[asset])
        q = _question(
            stem_latex="已知 $x=1$，求值",
            answer_latex="A",
        )
        payload: dict = {}
        _harden_question(q, block, payload)
        self.assertIn("[图]", q.stem_latex)

    def test_asset_block_with_reference_not_changed(self):
        asset = QuestionAsset(
            id="img1", type="image", storage_url="",
            page=1, bbox=(0.1, 0.1, 0.3, 0.3),
        )
        block = _block(assets=[asset])
        q = _question(
            stem_latex="如图所示，已知 $x=1$",
            answer_latex="A",
        )
        payload: dict = {}
        _harden_question(q, block, payload)
        self.assertNotIn("[图]", q.stem_latex)  # already has 如图

    def test_block_without_assets_not_changed(self):
        block = _block(assets=[])
        q = _question(stem_latex="已知 $x=1$")
        original = q.stem_latex
        payload: dict = {}
        _harden_question(q, block, payload)
        self.assertEqual(q.stem_latex, original)


# ---------------------------------------------------------------------------
# TestHardeningIntegration
# ---------------------------------------------------------------------------


class TestHardeningIntegration(unittest.TestCase):
    """ADR 015: hardening + gating integration."""

    def test_hardened_question_passes_gating(self):
        """After hardening, a question that would warn should pass."""
        from question_bank.services.quality import gate_question

        # Scenario: proof with no analysis, but with asset and no image ref
        asset = QuestionAsset(
            id="img1", type="image", storage_url="",
            page=1, bbox=(0.1, 0.1, 0.3, 0.3),
        )
        block = _block(assets=[asset])
        q = _question(
            question_type="proof",
            stem_latex="证明 $x^2 + y^2 = z^2$",
            choices=[],
            answer_latex="proof goes here",
            analysis_latex="",
        )
        payload: dict = {}
        _harden_question(q, block, payload)

        result = gate_question(q, block)
        # missing_analysis should be fixed (analysis filled)
        self.assertNotIn("missing_analysis", result.warning_codes)
        # asset_without_text_reference should be fixed
        self.assertNotIn("asset_without_text_reference", result.warning_codes)
        self.assertEqual(result.gate, "pass")

    def test_hardened_answer_not_in_choices_passes_gating(self):
        """After answer normalization, answer_not_in_choices should not fire."""
        from question_bank.services.quality import gate_question

        q = _question(
            question_type="single_choice",
            stem_latex="已知 $x=1$",
            choices=[_choice("A", "$x^2 + y^2 = z^2$"), _choice("B", "$a+b=c$")],
            answer_latex="$x^2 + y^2 = z^2$",
        )
        payload: dict = {}
        _harden_question(q, _block(), payload)

        result = gate_question(q)
        self.assertNotIn("answer_not_in_choices", result.warning_codes)
        self.assertEqual(result.gate, "pass")

    def test_hardened_too_few_choices_passes_gating(self):
        """After choice padding, too_few_choices should not fire."""
        from question_bank.services.quality import gate_question

        q = _question(
            question_type="single_choice",
            stem_latex="已知 $x=1$",
            choices=[],
            answer_latex="A",
        )
        block = _block(raw_markdown="A. x=1\nB. x=2\nC. x=3\nD. x=4")
        payload: dict = {}
        _harden_question(q, block, payload)

        result = gate_question(q)
        self.assertNotIn("too_few_choices", result.warning_codes)
        self.assertEqual(result.gate, "pass")

    def test_all_four_fixes_applied_simultaneously(self):
        """A worst-case question gets all four fixes and passes gating."""
        from question_bank.services.quality import gate_question

        asset = QuestionAsset(
            id="img1", type="image", storage_url="",
            page=1, bbox=(0.1, 0.1, 0.3, 0.3),
        )
        block = _block(
            assets=[asset],
            raw_markdown="A. $x^2 + y^2 = z^2$\nB. $a+b=c$\nC. $d+e=f$\nD. none",
        )
        q = _question(
            question_type="single_choice",
            stem_latex="已知 $x=1$",
            choices=[_choice("A", "$x^2 + y^2 = z^2$")],
            answer_latex="$a+b=c$",
            analysis_latex="",
        )
        payload: dict = {}
        _harden_question(q, block, payload)

        # After hardening: choices padded, answer normalized, image ref added
        result = gate_question(q, block)
        self.assertNotIn("too_few_choices", result.warning_codes)
        self.assertNotIn("answer_not_in_choices", result.warning_codes)
        self.assertNotIn("asset_without_text_reference", result.warning_codes)
        self.assertEqual(result.gate, "pass")


if __name__ == "__main__":
    unittest.main()
