from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class QuestionType(StrEnum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    FILL_BLANK = "fill_blank"
    SHORT_ANSWER = "short_answer"
    PROOF = "proof"
    UNKNOWN = "unknown"


class AssetType(StrEnum):
    IMAGE = "image"
    GEOMETRY = "geometry"
    CHART = "chart"
    TABLE = "table"
    FORMULA_IMAGE = "formula_image"


class ReviewStatus(StrEnum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REPARSE = "needs_reparse"
    DISCARDED = "discarded"


@dataclass(slots=True)
class Choice:
    label: str
    content_latex: str
    sort_order: int = 0


@dataclass(slots=True)
class QuestionAsset:
    id: str
    type: AssetType | str
    storage_url: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    confidence: float = 1.0
    caption: str = ""


@dataclass(slots=True)
class QuestionBlock:
    id: str
    paper_id: str
    question_number: str
    raw_markdown: str
    section_title: str = ""
    pages: list[int] = field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    assets: list[QuestionAsset] = field(default_factory=list)
    split_confidence: float = 1.0
    needs_review: bool = False


@dataclass(slots=True)
class Question:
    id: str
    question_type: QuestionType | str
    stem_latex: str
    choices: list[Choice] = field(default_factory=list)
    answer_latex: str = ""
    analysis_latex: str = ""
    knowledge_points: list[str] = field(default_factory=list)
    difficulty: int | None = None
    assets: list[QuestionAsset] = field(default_factory=list)
    source_location: dict[str, Any] = field(default_factory=dict)
    review_status: ReviewStatus = ReviewStatus.DRAFT


@dataclass(slots=True)
class QualityIssue:
    code: str
    message: str
    severity: str = "error"
    field: str | None = None


@dataclass(slots=True)
class QualityReport:
    question_id: str
    issues: list[QualityIssue] = field(default_factory=list)
    model_warnings: list[str] = field(default_factory=list)
    overall_score: float = 1.0
    needs_review: bool = False
