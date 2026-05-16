import unittest

from question_bank.domain.models import Choice, Question, QuestionBlock, QuestionType
from question_bank.services.type_inference import infer_question_type


class TypeInferenceTest(unittest.TestCase):
    def test_infers_single_choice_when_choices_exist(self):
        question = Question(
            id="q_001",
            question_type=QuestionType.UNKNOWN,
            stem_latex="下列正确的是（ ）",
            choices=[Choice(label="A", content_latex="$1$"), Choice(label="B", content_latex="$2$")],
        )
        block = QuestionBlock(id="qb_001", paper_id="paper_001", question_number="1", raw_markdown="")

        self.assertEqual(infer_question_type(question, block), QuestionType.SINGLE_CHOICE)

    def test_infers_fill_blank_from_blank_marker(self):
        question = Question(id="q_001", question_type="unknown", stem_latex="计算 $2^3=$____。")
        block = QuestionBlock(id="qb_001", paper_id="paper_001", question_number="1", raw_markdown="")

        self.assertEqual(infer_question_type(question, block), QuestionType.FILL_BLANK)

    def test_infers_proof_from_section_title(self):
        question = Question(id="q_001", question_type="unknown", stem_latex="证明 $AB=CD$。")
        block = QuestionBlock(
            id="qb_001",
            paper_id="paper_001",
            question_number="1",
            raw_markdown="",
            section_title="三、证明题",
        )

        self.assertEqual(infer_question_type(question, block), QuestionType.PROOF)

    def test_keeps_specific_model_type(self):
        question = Question(id="q_001", question_type=QuestionType.SINGLE_CHOICE, stem_latex="题干")
        block = QuestionBlock(id="qb_001", paper_id="paper_001", question_number="1", raw_markdown="")

        self.assertEqual(infer_question_type(question, block), QuestionType.SINGLE_CHOICE)


if __name__ == "__main__":
    unittest.main()

