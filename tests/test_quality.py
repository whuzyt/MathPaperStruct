import unittest

from question_bank.domain.models import Choice, Question, QuestionAsset, QuestionType
from question_bank.services.quality import validate_question


class QualityValidationTest(unittest.TestCase):
    def test_valid_single_choice_question_passes(self):
        question = Question(
            id="q_001",
            question_type=QuestionType.SINGLE_CHOICE,
            stem_latex="已知 $y=2x+1$，当 $x=3$ 时，$y$ 的值为（ ）",
            choices=[
                Choice(label="A", content_latex="$5$"),
                Choice(label="B", content_latex="$6$"),
                Choice(label="C", content_latex="$7$"),
                Choice(label="D", content_latex="$8$"),
            ],
            answer_latex="C",
            analysis_latex="代入得 $y=2\\times3+1=7$。",
        )

        report = validate_question(question)

        self.assertFalse(report.needs_review)
        self.assertEqual(report.overall_score, 1.0)
        self.assertEqual(report.issues, [])

    def test_flags_answer_that_does_not_match_choices(self):
        question = Question(
            id="q_002",
            question_type=QuestionType.SINGLE_CHOICE,
            stem_latex="选择正确答案。",
            choices=[Choice(label="A", content_latex="$1$"), Choice(label="B", content_latex="$2$")],
            answer_latex="C",
        )

        report = validate_question(question)

        self.assertTrue(report.needs_review)
        self.assertIn("answer_not_in_choices", [issue.code for issue in report.issues])

    def test_flags_missing_image_reference(self):
        question = Question(
            id="q_003",
            question_type=QuestionType.SHORT_ANSWER,
            stem_latex="如图，求阴影部分面积。",
            answer_latex="$12$",
            analysis_latex="根据图形分割计算。",
        )

        report = validate_question(question)

        self.assertTrue(report.needs_review)
        self.assertIn("missing_referenced_image", [issue.code for issue in report.issues])

    def test_question_with_referenced_image_passes_image_rule(self):
        question = Question(
            id="q_004",
            question_type=QuestionType.SHORT_ANSWER,
            stem_latex="如图，求阴影部分面积。",
            answer_latex="$12$",
            analysis_latex="根据图形分割计算。",
            assets=[QuestionAsset(id="asset_1", type="image", storage_url="s3://bucket/q4.png")],
        )

        report = validate_question(question)

        self.assertNotIn("missing_referenced_image", [issue.code for issue in report.issues])

    def test_flags_single_choice_with_too_few_choices(self):
        question = Question(
            id="q_005",
            question_type=QuestionType.SINGLE_CHOICE,
            stem_latex="选择正确答案。",
            choices=[Choice(label="A", content_latex="$1$"), Choice(label="B", content_latex="$2$")],
            answer_latex="A",
        )

        report = validate_question(question)

        self.assertIn("too_few_choices", [issue.code for issue in report.issues])

    def test_flags_single_choice_missing_answer(self):
        question = Question(
            id="q_006",
            question_type=QuestionType.SINGLE_CHOICE,
            stem_latex="选择正确答案。",
            choices=[
                Choice(label="A", content_latex="$1$"),
                Choice(label="B", content_latex="$2$"),
                Choice(label="C", content_latex="$3$"),
                Choice(label="D", content_latex="$4$"),
            ],
        )

        report = validate_question(question)

        self.assertIn("missing_answer", [issue.code for issue in report.issues])

    def test_flags_unbalanced_latex_dollar_delimiters(self):
        question = Question(
            id="q_007",
            question_type=QuestionType.FILL_BLANK,
            stem_latex="计算 $2^3。",
            answer_latex="$8$",
        )

        report = validate_question(question)

        self.assertIn("unbalanced_latex_delimiters", [issue.code for issue in report.issues])

    def test_flags_proof_without_analysis(self):
        question = Question(
            id="q_008",
            question_type=QuestionType.PROOF,
            stem_latex="证明 $AB=CD$。",
            answer_latex="见证明。",
        )

        report = validate_question(question)

        self.assertIn("missing_analysis", [issue.code for issue in report.issues])


if __name__ == "__main__":
    unittest.main()
