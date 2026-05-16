from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from question_bank.pipeline import ProcessingPipeline, ProcessingResult, ProcessingResultRepository
from question_bank.services.deepseek import DeepSeekClientProtocol
from question_bank.services.mineru import MinerURunnerProtocol


class PDFIngestionError(RuntimeError):
    """Raised when a PDF cannot be converted into a processable Markdown artifact."""


@dataclass(slots=True)
class PDFIngestionService:
    mineru_runner: MinerURunnerProtocol
    deepseek_client: DeepSeekClientProtocol
    repository: ProcessingResultRepository

    def ingest_pdf(self, paper_id: str, pdf_path: Path, output_dir: Path) -> ProcessingResult:
        mineru_result = self.mineru_runner.parse_pdf(pdf_path, output_dir)
        markdown = self._read_markdown(mineru_result.markdown_path)
        pipeline = ProcessingPipeline(deepseek_client=self.deepseek_client)
        return pipeline.process_and_save_markdown(paper_id, markdown, self.repository)

    @staticmethod
    def _read_markdown(markdown_path: Path | None) -> str:
        if markdown_path is None:
            raise PDFIngestionError("MinerU result did not include a Markdown path.")
        if not markdown_path.exists():
            raise PDFIngestionError(f"MinerU Markdown output does not exist: {markdown_path}")
        markdown = markdown_path.read_text(encoding="utf-8").strip()
        if not markdown:
            raise PDFIngestionError(f"MinerU Markdown output is empty: {markdown_path}")
        return markdown

