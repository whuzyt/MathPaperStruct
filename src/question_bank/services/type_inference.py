from __future__ import annotations

import re

from question_bank.domain.models import Question, QuestionBlock, QuestionType


BLANK_PATTERN = re.compile(r"(__+|_{2,}|（\s*）|\(\s*\)|填空)")


def infer_question_type(question: Question, block: QuestionBlock) -> QuestionType:
    current_type = str(question.question_type)
    if current_type not in {QuestionType.UNKNOWN, QuestionType.SHORT_ANSWER, "unknown", "short_answer"}:
        return QuestionType(current_type)

    section_title = block.section_title
    if question.choices:
        return QuestionType.SINGLE_CHOICE
    if "证明" in section_title or question.stem_latex.strip().startswith("证明"):
        return QuestionType.PROOF
    if BLANK_PATTERN.search(question.stem_latex):
        return QuestionType.FILL_BLANK
    if "选择" in section_title:
        return QuestionType.SINGLE_CHOICE
    if "填空" in section_title:
        return QuestionType.FILL_BLANK
    if any(keyword in section_title for keyword in ["解答", "计算", "应用", "综合", "压轴"]):
        return QuestionType.SHORT_ANSWER
    return QuestionType(current_type)

