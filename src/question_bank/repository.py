from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from question_bank.domain.models import QualityIssue, Question, QuestionAsset, QuestionBlock
from question_bank.pipeline import ProcessingResult


class CursorProtocol(Protocol):
    def execute(self, sql: str, params: dict[str, Any]) -> Any:
        """Execute a parameterized SQL statement."""


class ConnectionProtocol(Protocol):
    def cursor(self) -> CursorProtocol:
        """Return a cursor."""

    def commit(self) -> Any:
        """Commit the current transaction."""

    def rollback(self) -> Any:
        """Roll back the current transaction."""


@dataclass(frozen=True, slots=True)
class ReviewQueueItem:
    question_id: str
    question_type: str
    stem_latex: str
    overall_score: float
    error_codes: list[str]
    model_warnings: list[str]


class PostgresQuestionBankRepository:
    def __init__(self, connection: ConnectionProtocol):
        self.connection = connection

    def save_processing_result(self, result: ProcessingResult) -> None:
        cursor = self.connection.cursor()
        try:
            for block in result.blocks:
                cursor.execute(_INSERT_QUESTION_BLOCK, _block_params(block))

            block_ids = [block.id for block in result.blocks]
            for index, question in enumerate(result.questions):
                block_id = block_ids[index] if index < len(block_ids) else None
                cursor.execute(_INSERT_QUESTION, _question_params(question, block_id))
                for choice in question.choices:
                    cursor.execute(
                        _INSERT_CHOICE,
                        {
                            "id": f"{question.id}_choice_{choice.label}",
                            "question_id": question.id,
                            "label": choice.label,
                            "content_latex": choice.content_latex,
                            "sort_order": choice.sort_order,
                        },
                    )
                for asset in question.assets:
                    cursor.execute(_INSERT_QUESTION_ASSET, _asset_params(question.id, asset))

            for report in result.quality_reports:
                cursor.execute(
                    _INSERT_QUALITY_REPORT,
                    {
                        "id": f"{report.question_id}_quality",
                        "question_id": report.question_id,
                        "rule_errors": _json_dumps([_issue_to_dict(issue) for issue in report.issues]),
                        "render_errors": _json_dumps([]),
                        "model_warnings": _json_dumps(report.model_warnings),
                        "overall_score": report.overall_score,
                        "needs_review": report.needs_review,
                    },
                )

            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def list_review_queue(self, limit: int = 50) -> list[ReviewQueueItem]:
        cursor = self.connection.cursor()
        cursor.execute(_SELECT_REVIEW_QUEUE, {"limit": limit})
        return [_review_item_from_row(row) for row in cursor.fetchall()]


_INSERT_QUESTION_BLOCK = """
INSERT INTO question_blocks (
  id, paper_id, parse_run_id, question_number, section_title, raw_markdown,
  pages, bbox_json, split_confidence, needs_review
) VALUES (
  %(id)s, %(paper_id)s, %(parse_run_id)s, %(question_number)s, %(section_title)s,
  %(raw_markdown)s, %(pages)s, %(bbox_json)s, %(split_confidence)s, %(needs_review)s
) ON CONFLICT (id) DO UPDATE SET
  section_title = EXCLUDED.section_title,
  raw_markdown = EXCLUDED.raw_markdown,
  pages = EXCLUDED.pages,
  bbox_json = EXCLUDED.bbox_json,
  split_confidence = EXCLUDED.split_confidence,
  needs_review = EXCLUDED.needs_review
"""

_INSERT_QUESTION = """
INSERT INTO questions (
  id, question_block_id, subject, grade, question_type, stem_latex,
  answer_latex, analysis_latex, difficulty, quality_status, review_status,
  source_location_json, knowledge_points
) VALUES (
  %(id)s, %(question_block_id)s, %(subject)s, %(grade)s, %(question_type)s,
  %(stem_latex)s, %(answer_latex)s, %(analysis_latex)s, %(difficulty)s,
  %(quality_status)s, %(review_status)s, %(source_location_json)s, %(knowledge_points)s
) ON CONFLICT (id) DO UPDATE SET
  question_block_id = EXCLUDED.question_block_id,
  question_type = EXCLUDED.question_type,
  stem_latex = EXCLUDED.stem_latex,
  answer_latex = EXCLUDED.answer_latex,
  analysis_latex = EXCLUDED.analysis_latex,
  difficulty = EXCLUDED.difficulty,
  review_status = EXCLUDED.review_status,
  source_location_json = EXCLUDED.source_location_json,
  knowledge_points = EXCLUDED.knowledge_points,
  updated_at = now()
"""

_INSERT_CHOICE = """
INSERT INTO choices (
  id, question_id, label, content_latex, sort_order
) VALUES (
  %(id)s, %(question_id)s, %(label)s, %(content_latex)s, %(sort_order)s
) ON CONFLICT (question_id, label) DO UPDATE SET
  content_latex = EXCLUDED.content_latex,
  sort_order = EXCLUDED.sort_order
"""

_INSERT_QUESTION_ASSET = """
INSERT INTO question_assets (
  id, question_id, type, storage_url, page, bbox_json, caption, confidence
) VALUES (
  %(id)s, %(question_id)s, %(type)s, %(storage_url)s, %(page)s,
  %(bbox_json)s, %(caption)s, %(confidence)s
) ON CONFLICT (id) DO UPDATE SET
  type = EXCLUDED.type,
  storage_url = EXCLUDED.storage_url,
  page = EXCLUDED.page,
  bbox_json = EXCLUDED.bbox_json,
  caption = EXCLUDED.caption,
  confidence = EXCLUDED.confidence
"""

_INSERT_QUALITY_REPORT = """
INSERT INTO quality_reports (
  id, question_id, rule_errors, render_errors, model_warnings, overall_score, needs_review
) VALUES (
  %(id)s, %(question_id)s, %(rule_errors)s, %(render_errors)s,
  %(model_warnings)s, %(overall_score)s, %(needs_review)s
) ON CONFLICT (id) DO UPDATE SET
  rule_errors = EXCLUDED.rule_errors,
  render_errors = EXCLUDED.render_errors,
  model_warnings = EXCLUDED.model_warnings,
  overall_score = EXCLUDED.overall_score,
  needs_review = EXCLUDED.needs_review
"""

_SELECT_REVIEW_QUEUE = """
SELECT
  q.id AS question_id,
  q.question_type,
  q.stem_latex,
  qr.overall_score,
  qr.rule_errors,
  qr.model_warnings
FROM quality_reports qr
JOIN questions q ON q.id = qr.question_id
WHERE qr.needs_review = true
ORDER BY qr.overall_score ASC, q.created_at ASC
LIMIT %(limit)s
"""


def _block_params(block: QuestionBlock) -> dict[str, Any]:
    return {
        "id": block.id,
        "paper_id": block.paper_id,
        "parse_run_id": None,
        "question_number": block.question_number,
        "section_title": block.section_title,
        "raw_markdown": block.raw_markdown,
        "pages": _json_dumps(block.pages),
        "bbox_json": _json_dumps(block.bbox) if block.bbox else None,
        "split_confidence": block.split_confidence,
        "needs_review": block.needs_review,
    }


def _question_params(question: Question, block_id: str | None) -> dict[str, Any]:
    return {
        "id": question.id,
        "question_block_id": block_id,
        "subject": "math",
        "grade": None,
        "question_type": str(question.question_type),
        "stem_latex": question.stem_latex,
        "answer_latex": question.answer_latex,
        "analysis_latex": question.analysis_latex,
        "difficulty": question.difficulty,
        "quality_status": "needs_review" if not question.stem_latex else "draft",
        "review_status": str(question.review_status),
        "source_location_json": _json_dumps(question.source_location),
        "knowledge_points": _json_dumps(question.knowledge_points),
    }


def _asset_params(question_id: str, asset: QuestionAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "question_id": question_id,
        "type": str(asset.type),
        "storage_url": asset.storage_url,
        "page": asset.page,
        "bbox_json": _json_dumps(asset.bbox) if asset.bbox else None,
        "caption": asset.caption,
        "confidence": asset.confidence,
    }


def _issue_to_dict(issue: QualityIssue) -> dict[str, Any]:
    return {
        "code": issue.code,
        "message": issue.message,
        "severity": issue.severity,
        "field": issue.field,
    }


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _review_item_from_row(row: Any) -> ReviewQueueItem:
    if isinstance(row, dict):
        question_id = row["question_id"]
        question_type = row["question_type"]
        stem_latex = row["stem_latex"]
        overall_score = row["overall_score"]
        rule_errors = row["rule_errors"]
        model_warnings = row["model_warnings"]
    else:
        question_id, question_type, stem_latex, overall_score, rule_errors, model_warnings = row

    errors = _json_loads(rule_errors, default=[])
    warnings = _json_loads(model_warnings, default=[])
    return ReviewQueueItem(
        question_id=question_id,
        question_type=question_type,
        stem_latex=stem_latex,
        overall_score=float(overall_score),
        error_codes=[str(item.get("code", "")) for item in errors if isinstance(item, dict)],
        model_warnings=[str(item) for item in warnings],
    )


def _json_loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value
