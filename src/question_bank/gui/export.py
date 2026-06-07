from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from question_bank.domain.models import Choice, QualityReport, Question, QuestionBlock
from question_bank.pipeline import ProcessingResult


@dataclass(frozen=True, slots=True)
class ExportPaths:
    json_path: Path
    markdown_path: Path


def processing_result_to_dicts(result: ProcessingResult) -> list[dict[str, Any]]:
    reports_by_question = {report.question_id: report for report in result.quality_reports}
    blocks_by_index = {
        index: block
        for index, block in enumerate(result.blocks)
    }

    rows: list[dict[str, Any]] = []
    for index, question in enumerate(result.questions):
        block = blocks_by_index.get(index)
        report = reports_by_question.get(question.id)
        rows.append(_question_to_dict(question, block, report))
    return rows


def export_questions(result: ProcessingResult, output_dir: Path) -> ExportPaths:
    output_dir.mkdir(parents=True, exist_ok=True)
    questions = processing_result_to_dicts(result)
    payload = {
        "paper_id": result.paper_id,
        "question_count": len(questions),
        "questions": questions,
    }

    json_path = output_dir / f"{result.paper_id}_questions.json"
    markdown_path = output_dir / f"{result.paper_id}_questions.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(
        _questions_to_markdown(result.paper_id, questions),
        encoding="utf-8",
    )
    return ExportPaths(json_path=json_path, markdown_path=markdown_path)


def _question_to_dict(
    question: Question,
    block: QuestionBlock | None,
    report: QualityReport | None,
) -> dict[str, Any]:
    return {
        "id": question.id,
        "question_number": block.question_number if block else "",
        "question_type": str(question.question_type),
        "section_title": block.section_title if block else "",
        "pages": list(block.pages) if block else [],
        "stem_latex": question.stem_latex,
        "choices": [_choice_to_dict(choice) for choice in question.choices],
        "answer_latex": question.answer_latex,
        "analysis_latex": question.analysis_latex,
        "knowledge_points": list(question.knowledge_points),
        "difficulty": question.difficulty,
        "assets": [
            {
                "id": asset.id,
                "type": str(asset.type),
                "storage_url": asset.storage_url,
                "page": asset.page,
                "bbox": list(asset.bbox) if asset.bbox else None,
                "caption": asset.caption,
            }
            for asset in (question.assets or (block.assets if block else []))
        ],
        "quality": _quality_to_dict(report),
        "raw_markdown": block.raw_markdown if block else "",
    }


def _choice_to_dict(choice: Choice) -> dict[str, Any]:
    return {
        "label": choice.label,
        "content_latex": choice.content_latex,
        "sort_order": choice.sort_order,
    }


def _quality_to_dict(report: QualityReport | None) -> dict[str, Any]:
    if report is None:
        return {
            "needs_review": False,
            "overall_score": 1.0,
            "issues": [],
            "model_warnings": [],
        }
    return {
        "needs_review": report.needs_review,
        "overall_score": report.overall_score,
        "issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "severity": issue.severity,
                "field": issue.field,
            }
            for issue in report.issues
        ],
        "model_warnings": list(report.model_warnings),
    }


def _questions_to_markdown(paper_id: str, questions: list[dict[str, Any]]) -> str:
    review_count = sum(1 for q in questions if q.get("quality", {}).get("needs_review"))
    lines = [
        f"# {paper_id} 题目导出",
        "",
        f"- 题目数：{len(questions)}",
        f"- 需复核：{review_count}",
        "",
    ]
    for index, question in enumerate(questions, start=1):
        number = question.get("question_number") or str(index)
        pages = ", ".join(str(p) for p in question.get("pages", [])) or "-"
        q_type = question.get("question_type") or "-"
        needs_review = "是" if question.get("quality", {}).get("needs_review") else "否"
        lines.extend([
            f"## 第 {number} 题",
            "",
            f"- 类型：{q_type}",
            f"- 页码：{pages}",
            f"- 需复核：{needs_review}",
            "",
            str(question.get("stem_latex", "")).strip(),
            "",
        ])
        choices = question.get("choices") or []
        if choices:
            lines.append("**选项**")
            for choice in choices:
                lines.append(
                    f"- {choice.get('label', '')}. {choice.get('content_latex', '')}"
                )
            lines.append("")
        answer = str(question.get("answer_latex", "")).strip()
        if answer:
            lines.extend([f"**答案**：{answer}", ""])
        analysis = str(question.get("analysis_latex", "")).strip()
        if analysis:
            lines.extend(["**解析**", "", analysis, ""])
        warnings = question.get("quality", {}).get("model_warnings", [])
        if warnings:
            lines.extend(["**模型提示**", ""])
            lines.extend(f"- {warning}" for warning in warnings)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
