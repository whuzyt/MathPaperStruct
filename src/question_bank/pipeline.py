from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from question_bank.domain.models import Choice, QualityReport, Question, QuestionBlock
from question_bank.services.deepseek import DeepSeekClientProtocol
from question_bank.services.quality import validate_question
from question_bank.services.question_splitter import (
    parse_answer_entries,
    parse_answer_entry,
    parse_choices,
    split_markdown_into_blocks,
)
from question_bank.services.type_inference import infer_question_type


@dataclass(slots=True)
class ProcessingResult:
    paper_id: str
    blocks: list[QuestionBlock]
    questions: list[Question]
    quality_reports: list[QualityReport]


class ProcessingResultRepository(Protocol):
    def save_processing_result(self, result: ProcessingResult) -> None:
        """Persist a processing result."""


@dataclass(slots=True)
class ProcessingPipeline:
    deepseek_client: DeepSeekClientProtocol

    def process_markdown(self, paper_id: str, markdown: str) -> ProcessingResult:
        blocks = split_markdown_into_blocks(paper_id, markdown)
        answer_entries = parse_answer_entries(markdown)
        questions: list[Question] = []
        reports: list[QualityReport] = []

        for index, block in enumerate(blocks, start=1):
            payload = self.deepseek_client.structure_question(block.raw_markdown)
            question = self._question_from_payload(paper_id, index, payload)
            if not question.choices:
                question.choices = parse_choices(block.raw_markdown)
            if block.question_number in answer_entries:
                parsed_answer = parse_answer_entry(answer_entries[block.question_number])
                if not question.answer_latex and parsed_answer.answer_latex:
                    question.answer_latex = parsed_answer.answer_latex
                if not question.analysis_latex and parsed_answer.analysis_latex:
                    question.analysis_latex = parsed_answer.analysis_latex
            question.question_type = infer_question_type(question, block)
            questions.append(question)
            report = validate_question(question)
            report.model_warnings = [
                str(warning) for warning in payload.get("warnings", []) if str(warning).strip()
            ]
            if report.model_warnings:
                report.needs_review = True
            reports.append(report)

        return ProcessingResult(
            paper_id=paper_id,
            blocks=blocks,
            questions=questions,
            quality_reports=reports,
        )

    def process_and_save_markdown(
        self,
        paper_id: str,
        markdown: str,
        repository: ProcessingResultRepository,
    ) -> ProcessingResult:
        result = self.process_markdown(paper_id, markdown)
        repository.save_processing_result(result)
        return result

    @staticmethod
    def _question_from_payload(paper_id: str, index: int, payload: dict) -> Question:
        choices = [
            Choice(
                label=str(choice.get("label", "")).strip(),
                content_latex=str(choice.get("content_latex", "")).strip(),
                sort_order=position,
            )
            for position, choice in enumerate(payload.get("choices", []), start=1)
            if isinstance(choice, dict)
        ]
        return Question(
            id=f"{paper_id}_q_{index:04d}",
            question_type=str(payload.get("question_type", "unknown")),
            stem_latex=str(payload.get("stem_latex", "")).strip(),
            choices=choices,
            answer_latex=str(payload.get("answer_latex", "")).strip(),
            analysis_latex=str(payload.get("analysis_latex", "")).strip(),
            knowledge_points=list(payload.get("knowledge_points", [])),
            difficulty=payload.get("difficulty"),
        )
