from __future__ import annotations

import json
from datetime import UTC, datetime
from dataclasses import dataclass
from typing import Any, Protocol

from question_bank.domain.models import QualityIssue, Question, QuestionAsset, QuestionBlock
from question_bank.pipeline import ProcessingResult
from question_bank.services.canonicalize import (
    CanonicalQuestion,
    CanonicalizationEvent,
    QuestionVariant,
)
from question_bank.services.duplicate_review import DuplicateCandidateGroup, ReviewDecision


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

    # ── ADR 004: Duplicate Review Queue ──────────────────────────────────

    def save_duplicate_candidate_group(self, group: DuplicateCandidateGroup) -> None:
        cursor = self.connection.cursor()
        try:
            max_sim = max(
                (s.composite for s in group.pairwise_similarities.values()), default=0.0
            )
            cursor.execute(
                _INSERT_DUPLICATE_GROUP,
                {
                    "id": group.id,
                    "fingerprint": group.fingerprint,
                    "fingerprint_type": group.fingerprint_type,
                    "candidate_count": len(group.items),
                    "max_similarity": max_sim,
                    "status": group.status,
                },
            )

            cursor.execute(_DELETE_GROUP_ITEMS, {"group_id": group.id})

            for item in group.items:
                item_id = f"{group.id}_item_{item.block_id}"
                cursor.execute(
                    _INSERT_DUPLICATE_ITEM,
                    {
                        "id": item_id,
                        "group_id": group.id,
                        "block_id": item.block_id,
                        "question_id": item.question_id,
                        "paper_id": item.paper_id,
                        "section_path": item.section_path,
                        "question_number": item.question_number,
                        "source_position_key": item.source_position_key,
                        "text_fingerprint": item.text_fingerprint,
                        "latex_fingerprint": item.latex_fingerprint,
                        "asset_signature": item.asset_signature,
                    },
                )

            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def save_review_decision(self, decision: ReviewDecision) -> None:
        cursor = self.connection.cursor()
        decision_id = f"drd_{decision.group_id}_{decision.reviewer}_{decision.decision}"
        cursor.execute(
            _INSERT_REVIEW_DECISION,
            {
                "id": decision_id,
                "group_id": decision.group_id,
                "decision": decision.decision,
                "canonical_question_id": decision.canonical_question_id,
                "reviewer": decision.reviewer,
                "reason": decision.reason,
            },
        )
        self.connection.commit()

    def list_duplicate_groups(
        self, status: str | None = None, limit: int = 50
    ) -> list[dict]:
        cursor = self.connection.cursor()
        if status:
            cursor.execute(_SELECT_DUPLICATE_GROUPS_BY_STATUS, {"status": status, "limit": limit})
        else:
            cursor.execute(_SELECT_DUPLICATE_GROUPS, {"limit": limit})
        rows = cursor.fetchall()
        return [_dup_group_from_row(row) for row in rows]

    def get_duplicate_group(self, group_id: str) -> dict | None:
        cursor = self.connection.cursor()
        cursor.execute(_SELECT_DUPLICATE_GROUP_BY_ID, {"group_id": group_id})
        row = cursor.fetchone()
        if row is None:
            return None
        group = _dup_group_from_row(row)

        cursor.execute(_SELECT_DUPLICATE_ITEMS_BY_GROUP, {"group_id": group_id})
        group["items"] = [_dup_item_from_row(r) for r in cursor.fetchall()]

        cursor.execute(_SELECT_DUPLICATE_DECISIONS_BY_GROUP, {"group_id": group_id})
        group["decisions"] = [_dup_decision_from_row(r) for r in cursor.fetchall()]

        return group

    # ── ADR 005: Question Canonicalization ────────────────────────────────

    def save_canonical_question(self, cq: CanonicalQuestion) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            _INSERT_CANONICAL_QUESTION,
            {
                "id": cq.id,
                "canonical_fingerprint": cq.canonical_fingerprint,
                "representative_item_id": cq.representative_item_id,
                "stem_latex": cq.stem_latex,
                "answer_latex": cq.answer_latex,
                "analysis_latex": cq.analysis_latex,
                "question_type": cq.question_type,
                "difficulty": cq.difficulty,
                "status": cq.status,
                "created_from_group_id": cq.created_from_group_id,
            },
        )

    def save_question_variant(self, v: QuestionVariant) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            _INSERT_QUESTION_VARIANT,
            {
                "id": v.id,
                "canonical_question_id": v.canonical_question_id,
                "question_id": v.question_id,
                "paper_id": v.paper_id,
                "variant_type": v.variant_type,
                "source_position_key": v.source_position_key,
                "text_fingerprint": v.text_fingerprint,
                "latex_fingerprint": v.latex_fingerprint,
                "asset_signature": v.asset_signature,
                "is_active": v.is_active,
            },
        )

    def save_canonicalization_event(self, e: CanonicalizationEvent) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            _INSERT_CANONICALIZATION_EVENT,
            {
                "id": e.id,
                "canonical_question_id": e.canonical_question_id,
                "group_id": e.group_id,
                "event_type": e.event_type,
                "payload_json": e.payload_json,
                "created_by": e.created_by,
            },
        )

    def canonicalize_group(self, group_id: str, created_by: str) -> dict:
        from question_bank.services.canonicalize import (
            build_canonical_id,
            canonicalize_group as do_canonicalize,
        )

        group = self.get_duplicate_group(group_id)
        if group is None:
            raise ValueError(f"Group not found: {group_id}")

        canonical_id = build_canonical_id(group_id)
        cursor = self.connection.cursor()

        # Idempotency: check if canonical already exists for this group
        cursor.execute(_SELECT_CANONICAL_BY_GROUP_ID, {"group_id": group_id})
        existing = cursor.fetchone()

        if existing is not None:
            existing_dict = _canonical_from_row(existing)
            if existing_dict["status"] == "active":
                # Already active — return existing canonical
                result = {
                    "canonical": existing_dict,
                    "variants": [],
                    "event": None,
                }
                cursor.execute(
                    _SELECT_VARIANTS_BY_CANONICAL,
                    {"canonical_id": existing_dict["id"]},
                )
                result["variants"] = [
                    _variant_from_row(r) for r in cursor.fetchall()
                ]
                return result
            # Reverted — reactivate
            try:
                cursor.execute(
                    _UPDATE_CANONICAL_STATUS,
                    {"id": existing_dict["id"], "status": "active"},
                )
                cursor.execute(
                    _UPDATE_VARIANTS_ACTIVATE,
                    {"canonical_id": existing_dict["id"]},
                )
                import json as _json
                reactivate_event = CanonicalizationEvent(
                    id=_canonical_event_id(existing_dict["id"], "reactivated"),
                    canonical_question_id=existing_dict["id"],
                    group_id=group_id,
                    event_type="reactivated",
                    payload_json=_json.dumps({"reactivated_by": created_by}, ensure_ascii=False),
                    created_by=created_by,
                )
                cursor.execute(
                    _INSERT_CANONICALIZATION_EVENT,
                    {
                        "id": reactivate_event.id,
                        "canonical_question_id": reactivate_event.canonical_question_id,
                        "group_id": reactivate_event.group_id,
                        "event_type": reactivate_event.event_type,
                        "payload_json": reactivate_event.payload_json,
                        "created_by": reactivate_event.created_by,
                    },
                )
                cursor.execute(
                    _SELECT_VARIANTS_BY_CANONICAL,
                    {"canonical_id": existing_dict["id"]},
                )
                variants = [_variant_from_row(r) for r in cursor.fetchall()]
                self.connection.commit()
                return {
                    "canonical": {**existing_dict, "status": "active"},
                    "variants": variants,
                    "event": {
                        "id": reactivate_event.id,
                        "canonical_question_id": reactivate_event.canonical_question_id,
                        "group_id": reactivate_event.group_id,
                        "event_type": reactivate_event.event_type,
                        "payload_json": reactivate_event.payload_json,
                        "created_by": reactivate_event.created_by,
                    },
                }
            except Exception:
                self.connection.rollback()
                raise

        # Create new canonical
        try:
            result = do_canonicalize(group, created_by)
            cq = result["canonical"]
            variants = result["variants"]
            event = result["event"]

            self.save_canonical_question(cq)
            for v in variants:
                self.save_question_variant(v)
            self.save_canonicalization_event(event)

            cursor.execute(
                _UPDATE_GROUP_STATUS,
                {"id": group_id, "status": "resolved"},
            )
            self.connection.commit()

            return {
                "canonical": _canonical_to_dict(cq),
                "variants": [_variant_to_dict(v) for v in variants],
                "event": _event_to_dict(event),
            }
        except Exception:
            self.connection.rollback()
            raise

    def list_canonical_questions(
        self, status: str | None = None, limit: int = 50
    ) -> list[dict]:
        cursor = self.connection.cursor()
        if status:
            cursor.execute(
                _SELECT_CANONICAL_QUESTIONS_BY_STATUS,
                {"status": status, "limit": limit},
            )
        else:
            cursor.execute(_SELECT_CANONICAL_QUESTIONS, {"limit": limit})
        return [_canonical_from_row(row) for row in cursor.fetchall()]

    def get_canonical_question(self, canonical_id: str) -> dict | None:
        cursor = self.connection.cursor()
        cursor.execute(_SELECT_CANONICAL_QUESTION_BY_ID, {"id": canonical_id})
        row = cursor.fetchone()
        if row is None:
            return None
        canonical = _canonical_from_row(row)

        cursor.execute(
            _SELECT_VARIANTS_BY_CANONICAL,
            {"canonical_id": canonical_id},
        )
        canonical["variants"] = [
            _variant_from_row(r) for r in cursor.fetchall()
        ]
        return canonical

    def rollback_canonical(self, canonical_id: str, created_by: str) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                _UPDATE_CANONICAL_STATUS,
                {"id": canonical_id, "status": "reverted"},
            )
            cursor.execute(
                _UPDATE_VARIANTS_DEACTIVATE,
                {"canonical_id": canonical_id},
            )
            import json as _json
            payload = _json.dumps({"rolled_back_by": created_by}, ensure_ascii=False)
            cursor.execute(
                _INSERT_CANONICALIZATION_EVENT,
                {
                    "id": _canonical_event_id(canonical_id, "reverted"),
                    "canonical_question_id": canonical_id,
                    "group_id": "",
                    "event_type": "reverted",
                    "payload_json": payload,
                    "created_by": created_by,
                },
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise


def _canonical_to_dict(cq: CanonicalQuestion) -> dict:
    return {
        "id": cq.id,
        "canonical_fingerprint": cq.canonical_fingerprint,
        "representative_item_id": cq.representative_item_id,
        "stem_latex": cq.stem_latex,
        "answer_latex": cq.answer_latex,
        "analysis_latex": cq.analysis_latex,
        "question_type": cq.question_type,
        "difficulty": cq.difficulty,
        "status": cq.status,
        "created_from_group_id": cq.created_from_group_id,
    }


def _variant_to_dict(v: QuestionVariant) -> dict:
    return {
        "id": v.id,
        "canonical_question_id": v.canonical_question_id,
        "question_id": v.question_id,
        "paper_id": v.paper_id,
        "variant_type": v.variant_type,
        "source_position_key": v.source_position_key,
        "text_fingerprint": v.text_fingerprint,
        "latex_fingerprint": v.latex_fingerprint,
        "asset_signature": v.asset_signature,
        "is_active": v.is_active,
    }


def _event_to_dict(e: CanonicalizationEvent) -> dict:
    return {
        "id": e.id,
        "canonical_question_id": e.canonical_question_id,
        "group_id": e.group_id,
        "event_type": e.event_type,
        "payload_json": e.payload_json,
        "created_by": e.created_by,
    }


def _canonical_event_id(canonical_id: str, event_type: str) -> str:
    ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    return f"{canonical_id}_evt_{event_type}_{ts}"


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


# ---------------------------------------------------------------------------
# ADR 004: Duplicate Review Queue SQL
# ---------------------------------------------------------------------------

_INSERT_DUPLICATE_GROUP = """
INSERT INTO duplicate_candidate_groups (
  id, fingerprint, fingerprint_type, candidate_count, max_similarity, status
) VALUES (
  %(id)s, %(fingerprint)s, %(fingerprint_type)s,
  %(candidate_count)s, %(max_similarity)s, %(status)s
) ON CONFLICT (id) DO UPDATE SET
  candidate_count = EXCLUDED.candidate_count,
  max_similarity = EXCLUDED.max_similarity,
  status = EXCLUDED.status
"""

_INSERT_DUPLICATE_ITEM = """
INSERT INTO duplicate_candidate_items (
  id, group_id, block_id, question_id, paper_id, section_path,
  question_number, source_position_key, text_fingerprint,
  latex_fingerprint, asset_signature
) VALUES (
  %(id)s, %(group_id)s, %(block_id)s, %(question_id)s, %(paper_id)s,
  %(section_path)s, %(question_number)s, %(source_position_key)s,
  %(text_fingerprint)s, %(latex_fingerprint)s, %(asset_signature)s
) ON CONFLICT (id) DO UPDATE SET
  question_id = EXCLUDED.question_id,
  section_path = EXCLUDED.section_path
"""

_DELETE_GROUP_ITEMS = """
DELETE FROM duplicate_candidate_items WHERE group_id = %(group_id)s
"""

_INSERT_REVIEW_DECISION = """
INSERT INTO duplicate_review_decisions (
  id, group_id, decision, canonical_question_id, reviewer, reason
) VALUES (
  %(id)s, %(group_id)s, %(decision)s, %(canonical_question_id)s,
  %(reviewer)s, %(reason)s
) ON CONFLICT DO NOTHING
"""

_SELECT_DUPLICATE_GROUPS = """
SELECT
  dcg.id, dcg.fingerprint, dcg.fingerprint_type,
  dcg.candidate_count, dcg.max_similarity, dcg.status,
  dcg.created_at
FROM duplicate_candidate_groups dcg
ORDER BY dcg.candidate_count DESC, dcg.created_at DESC
LIMIT %(limit)s
"""

_SELECT_DUPLICATE_GROUPS_BY_STATUS = """
SELECT
  dcg.id, dcg.fingerprint, dcg.fingerprint_type,
  dcg.candidate_count, dcg.max_similarity, dcg.status,
  dcg.created_at
FROM duplicate_candidate_groups dcg
WHERE dcg.status = %(status)s
ORDER BY dcg.candidate_count DESC, dcg.created_at DESC
LIMIT %(limit)s
"""

_SELECT_DUPLICATE_GROUP_BY_ID = """
SELECT
  dcg.id, dcg.fingerprint, dcg.fingerprint_type,
  dcg.candidate_count, dcg.max_similarity, dcg.status,
  dcg.created_at
FROM duplicate_candidate_groups dcg
WHERE dcg.id = %(group_id)s
"""

_SELECT_DUPLICATE_ITEMS_BY_GROUP = """
SELECT
  id, group_id, block_id, question_id, paper_id, section_path,
  question_number, source_position_key, text_fingerprint,
  latex_fingerprint, asset_signature
FROM duplicate_candidate_items
WHERE group_id = %(group_id)s
ORDER BY paper_id, question_number
"""

_SELECT_DUPLICATE_DECISIONS_BY_GROUP = """
SELECT
  id, group_id, decision, canonical_question_id, reviewer, reason, created_at
FROM duplicate_review_decisions
WHERE group_id = %(group_id)s
ORDER BY created_at DESC
"""


# ---------------------------------------------------------------------------
# ADR 005: Question Canonicalization SQL
# ---------------------------------------------------------------------------

_INSERT_CANONICAL_QUESTION = """
INSERT INTO canonical_questions (
  id, canonical_fingerprint, representative_item_id,
  stem_latex, answer_latex, analysis_latex,
  question_type, difficulty, status, created_from_group_id
) VALUES (
  %(id)s, %(canonical_fingerprint)s, %(representative_item_id)s,
  %(stem_latex)s, %(answer_latex)s, %(analysis_latex)s,
  %(question_type)s, %(difficulty)s, %(status)s, %(created_from_group_id)s
) ON CONFLICT (id) DO UPDATE SET
  canonical_fingerprint = EXCLUDED.canonical_fingerprint,
  representative_item_id = EXCLUDED.representative_item_id,
  stem_latex = EXCLUDED.stem_latex,
  answer_latex = EXCLUDED.answer_latex,
  analysis_latex = EXCLUDED.analysis_latex,
  question_type = EXCLUDED.question_type,
  difficulty = EXCLUDED.difficulty,
  status = EXCLUDED.status,
  updated_at = now()
"""

_INSERT_QUESTION_VARIANT = """
INSERT INTO question_variants (
  id, canonical_question_id, question_id, paper_id, variant_type,
  source_position_key, text_fingerprint, latex_fingerprint,
  asset_signature, is_active
) VALUES (
  %(id)s, %(canonical_question_id)s, %(question_id)s, %(paper_id)s,
  %(variant_type)s, %(source_position_key)s, %(text_fingerprint)s,
  %(latex_fingerprint)s, %(asset_signature)s, %(is_active)s
) ON CONFLICT (id) DO UPDATE SET
  question_id = EXCLUDED.question_id,
  is_active = EXCLUDED.is_active
"""

_INSERT_CANONICALIZATION_EVENT = """
INSERT INTO canonicalization_events (
  id, canonical_question_id, group_id, event_type,
  payload_json, created_by
) VALUES (
  %(id)s, %(canonical_question_id)s, %(group_id)s,
  %(event_type)s, %(payload_json)s, %(created_by)s
) ON CONFLICT DO NOTHING
"""

_UPDATE_CANONICAL_STATUS = """
UPDATE canonical_questions
SET status = %(status)s, updated_at = now()
WHERE id = %(id)s
"""

_UPDATE_VARIANTS_DEACTIVATE = """
UPDATE question_variants
SET is_active = false
WHERE canonical_question_id = %(canonical_id)s
"""

_UPDATE_VARIANTS_ACTIVATE = """
UPDATE question_variants
SET is_active = true
WHERE canonical_question_id = %(canonical_id)s
"""

_UPDATE_GROUP_STATUS = """
UPDATE duplicate_candidate_groups
SET status = %(status)s
WHERE id = %(id)s
"""

_SELECT_CANONICAL_QUESTIONS = """
SELECT
  id, canonical_fingerprint, representative_item_id,
  stem_latex, answer_latex, analysis_latex,
  question_type, difficulty, status, created_from_group_id,
  created_at, updated_at
FROM canonical_questions
ORDER BY created_at DESC
LIMIT %(limit)s
"""

_SELECT_CANONICAL_QUESTIONS_BY_STATUS = """
SELECT
  id, canonical_fingerprint, representative_item_id,
  stem_latex, answer_latex, analysis_latex,
  question_type, difficulty, status, created_from_group_id,
  created_at, updated_at
FROM canonical_questions
WHERE status = %(status)s
ORDER BY created_at DESC
LIMIT %(limit)s
"""

_SELECT_CANONICAL_QUESTION_BY_ID = """
SELECT
  id, canonical_fingerprint, representative_item_id,
  stem_latex, answer_latex, analysis_latex,
  question_type, difficulty, status, created_from_group_id,
  created_at, updated_at
FROM canonical_questions
WHERE id = %(id)s
"""

_SELECT_CANONICAL_BY_GROUP_ID = """
SELECT
  id, canonical_fingerprint, representative_item_id,
  stem_latex, answer_latex, analysis_latex,
  question_type, difficulty, status, created_from_group_id,
  created_at, updated_at
FROM canonical_questions
WHERE created_from_group_id = %(group_id)s
"""

_SELECT_VARIANTS_BY_CANONICAL = """
SELECT
  id, canonical_question_id, question_id, paper_id, variant_type,
  source_position_key, text_fingerprint, latex_fingerprint,
  asset_signature, is_active, created_at
FROM question_variants
WHERE canonical_question_id = %(canonical_id)s
ORDER BY paper_id
"""


def _dup_group_from_row(row: Any) -> dict:
    if isinstance(row, dict):
        return {
            "id": row["id"],
            "fingerprint": row["fingerprint"],
            "fingerprint_type": row["fingerprint_type"],
            "candidate_count": row["candidate_count"],
            "max_similarity": row["max_similarity"],
            "status": row["status"],
            "created_at": str(row.get("created_at", "")),
        }
    id_, fp, fp_type, count, max_sim, status, created_at = row
    return {
        "id": id_, "fingerprint": fp, "fingerprint_type": fp_type,
        "candidate_count": count, "max_similarity": max_sim,
        "status": status, "created_at": str(created_at),
    }


def _dup_item_from_row(row: Any) -> dict:
    if isinstance(row, dict):
        return {
            "id": row["id"], "group_id": row["group_id"],
            "block_id": row["block_id"], "question_id": row.get("question_id"),
            "paper_id": row["paper_id"], "section_path": row["section_path"],
            "question_number": row["question_number"],
            "source_position_key": row["source_position_key"],
            "text_fingerprint": row["text_fingerprint"],
            "latex_fingerprint": row["latex_fingerprint"],
            "asset_signature": row["asset_signature"],
        }
    id_, gid, bid, qid, pid, sp, qn, spk, tf, lf, af = row
    return {
        "id": id_, "group_id": gid, "block_id": bid, "question_id": qid,
        "paper_id": pid, "section_path": sp, "question_number": qn,
        "source_position_key": spk, "text_fingerprint": tf,
        "latex_fingerprint": lf, "asset_signature": af,
    }


def _dup_decision_from_row(row: Any) -> dict:
    if isinstance(row, dict):
        return {
            "id": row["id"], "group_id": row["group_id"],
            "decision": row["decision"],
            "canonical_question_id": row.get("canonical_question_id"),
            "reviewer": row["reviewer"], "reason": row.get("reason", ""),
            "created_at": str(row.get("created_at", "")),
        }
    id_, gid, decision, cqid, reviewer, reason, created_at = row
    return {
        "id": id_, "group_id": gid, "decision": decision,
        "canonical_question_id": cqid, "reviewer": reviewer,
        "reason": reason, "created_at": str(created_at),
    }


def _canonical_from_row(row: Any) -> dict:
    if isinstance(row, dict):
        return {
            "id": row["id"],
            "canonical_fingerprint": row["canonical_fingerprint"],
            "representative_item_id": row["representative_item_id"],
            "stem_latex": row["stem_latex"],
            "answer_latex": row["answer_latex"],
            "analysis_latex": row["analysis_latex"],
            "question_type": row["question_type"],
            "difficulty": row["difficulty"],
            "status": row["status"],
            "created_from_group_id": row["created_from_group_id"],
            "created_at": str(row.get("created_at", "")),
            "updated_at": str(row.get("updated_at", "")),
        }
    (
        id_, cfp, rep_id, stem, answer, analysis,
        qtype, diff, status, group_id, created_at, updated_at,
    ) = row
    return {
        "id": id_, "canonical_fingerprint": cfp,
        "representative_item_id": rep_id,
        "stem_latex": stem, "answer_latex": answer, "analysis_latex": analysis,
        "question_type": qtype, "difficulty": diff, "status": status,
        "created_from_group_id": group_id,
        "created_at": str(created_at), "updated_at": str(updated_at),
    }


def _variant_from_row(row: Any) -> dict:
    if isinstance(row, dict):
        return {
            "id": row["id"],
            "canonical_question_id": row["canonical_question_id"],
            "question_id": row.get("question_id"),
            "paper_id": row["paper_id"],
            "variant_type": row["variant_type"],
            "source_position_key": row["source_position_key"],
            "text_fingerprint": row["text_fingerprint"],
            "latex_fingerprint": row["latex_fingerprint"],
            "asset_signature": row["asset_signature"],
            "is_active": row["is_active"],
            "created_at": str(row.get("created_at", "")),
        }
    (
        id_, cqid, qid, pid, vtype, spk, tf, lf, af, active, created_at,
    ) = row
    return {
        "id": id_, "canonical_question_id": cqid, "question_id": qid,
        "paper_id": pid, "variant_type": vtype,
        "source_position_key": spk, "text_fingerprint": tf,
        "latex_fingerprint": lf, "asset_signature": af,
        "is_active": active, "created_at": str(created_at),
    }


def _event_from_row(row: Any) -> dict:
    if isinstance(row, dict):
        return {
            "id": row["id"],
            "canonical_question_id": row["canonical_question_id"],
            "group_id": row["group_id"],
            "event_type": row["event_type"],
            "payload_json": row.get("payload_json", "{}"),
            "created_by": row.get("created_by", ""),
            "created_at": str(row.get("created_at", "")),
        }
    id_, cqid, gid, etype, payload, created_by, created_at = row
    return {
        "id": id_, "canonical_question_id": cqid, "group_id": gid,
        "event_type": etype, "payload_json": payload,
        "created_by": created_by, "created_at": str(created_at),
    }
