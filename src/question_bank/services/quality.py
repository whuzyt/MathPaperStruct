from __future__ import annotations

import re
from dataclasses import dataclass, field

from question_bank.domain.models import QualityIssue, QualityReport, Question, QuestionBlock, QuestionType


IMAGE_REFERENCE_PATTERN = re.compile(r"(如图|下图|图中|由图|见图|\[图\])")


# ---------------------------------------------------------------------------
# ADR 013: Quality gating
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GatingResult:
    question_id: str
    gate: str  # "pass" | "warning" | "failed"
    warning_codes: list[str] = field(default_factory=list)


def gate_question(
    question: Question,
    block: QuestionBlock | None = None,
) -> GatingResult:
    """ADR 013: classify a structured question as pass/warning/failed.

    Returns a GatingResult that determines whether the question should be saved.
    Only ``failed`` questions are excluded from DB writes; ``warning`` questions
    are saved with their warning codes recorded in the run report.
    """
    warning_codes: list[str] = []

    # Failed: empty stem
    if not question.stem_latex.strip():
        return GatingResult(question.id, "failed", ["empty_stem"])

    # Warning: single_choice with < 2 choices
    if str(question.question_type) == QuestionType.SINGLE_CHOICE:
        if len(question.choices) < 2:
            warning_codes.append("too_few_choices")

    # Warning: single_choice answer not in choice labels
    if str(question.question_type) == QuestionType.SINGLE_CHOICE and question.choices:
        choice_labels = {c.label.strip().upper() for c in question.choices}
        answer = question.answer_latex.strip().upper()
        if answer and choice_labels and answer not in choice_labels:
            warning_codes.append("answer_not_in_choices")

    # Warning: proof/short_answer with no analysis
    if str(question.question_type) in {QuestionType.PROOF, QuestionType.SHORT_ANSWER}:
        if not question.analysis_latex.strip():
            warning_codes.append("missing_analysis")

    # Warning: unbalanced LaTeX delimiters in any text field
    for _field, value in [
        ("stem_latex", question.stem_latex),
        ("answer_latex", question.answer_latex),
        ("analysis_latex", question.analysis_latex),
    ]:
        if _has_unbalanced_latex_delimiters(value):
            warning_codes.append("unbalanced_latex_delimiters")
            break

    # Warning: block has image assets but text has no image reference
    if block is not None and block.assets:
        combined = question.stem_latex + question.answer_latex + question.analysis_latex
        if not IMAGE_REFERENCE_PATTERN.search(combined):
            warning_codes.append("asset_without_text_reference")

    gate = "warning" if warning_codes else "pass"
    return GatingResult(question.id, gate, warning_codes)


def validate_question(question: Question) -> QualityReport:
    issues: list[QualityIssue] = []

    if not question.stem_latex.strip():
        issues.append(QualityIssue("missing_stem", "题干为空。", field="stem_latex"))

    question_type = str(question.question_type)
    for field_name, value in [
        ("stem_latex", question.stem_latex),
        ("answer_latex", question.answer_latex),
        ("analysis_latex", question.analysis_latex),
    ]:
        if _has_unbalanced_latex_delimiters(value):
            issues.append(
                QualityIssue(
                    "unbalanced_latex_delimiters",
                    "LaTeX 美元符号疑似不闭合。",
                    field=field_name,
                )
            )

    if question_type == QuestionType.SINGLE_CHOICE:
        if not question.choices:
            issues.append(QualityIssue("missing_choices", "选择题缺少选项。", field="choices"))
        elif len(question.choices) < 4:
            issues.append(QualityIssue("too_few_choices", "选择题选项少于 4 个。", field="choices"))
        choice_labels = {choice.label.strip().upper() for choice in question.choices}
        answer = question.answer_latex.strip().upper()
        if not answer:
            issues.append(QualityIssue("missing_answer", "选择题缺少答案。", field="answer_latex"))
        if answer and choice_labels and answer not in choice_labels:
            issues.append(
                QualityIssue("answer_not_in_choices", "选择题答案未命中任何选项。", field="answer_latex")
            )

    if question_type in {QuestionType.FILL_BLANK, QuestionType.SHORT_ANSWER, QuestionType.PROOF}:
        if not question.answer_latex.strip():
            issues.append(QualityIssue("missing_answer", "非选择题缺少答案。", field="answer_latex"))

    if question_type in {QuestionType.PROOF, QuestionType.SHORT_ANSWER}:
        if not question.analysis_latex.strip():
            issues.append(QualityIssue("missing_analysis", "解答/证明题缺少解析。", field="analysis_latex"))

    if IMAGE_REFERENCE_PATTERN.search(question.stem_latex) and not question.assets:
        issues.append(
            QualityIssue("missing_referenced_image", "题干引用图片，但题目没有关联资源。", field="assets")
        )

    overall_score = max(0.0, 1.0 - len(issues) * 0.2)
    return QualityReport(
        question_id=question.id,
        issues=issues,
        overall_score=round(overall_score, 2),
        needs_review=bool(issues),
    )


def _has_unbalanced_latex_delimiters(value: str) -> bool:
    if not value:
        return False
    escaped = False
    count = 0
    for char in value:
        if char == "\\" and not escaped:
            escaped = True
            continue
        if char == "$" and not escaped:
            count += 1
        escaped = False
    return count % 2 == 1
