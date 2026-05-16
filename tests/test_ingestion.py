import tempfile
import unittest
from pathlib import Path

from question_bank.ingestion import PDFIngestionService, PDFIngestionError
from question_bank.services.deepseek import FakeDeepSeekClient
from question_bank.services.mineru import MinerUResult


class PDFIngestionServiceTest(unittest.TestCase):
    def test_ingests_pdf_by_running_mineru_and_saving_pipeline_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pdf_path = root / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")
            output_dir = root / "mineru-output"
            markdown_path = output_dir / "output.md"
            runner = FakeMinerURunner(markdown_path=markdown_path, markdown="1. 已知 $x=1$。")
            repository = RecordingRepository()
            service = PDFIngestionService(
                mineru_runner=runner,
                deepseek_client=FakeDeepSeekClient(),
                repository=repository,
            )

            result = service.ingest_pdf("paper_001", pdf_path, output_dir)

            self.assertEqual(runner.calls, [(pdf_path, output_dir)])
            self.assertEqual(result.paper_id, "paper_001")
            self.assertEqual(len(result.questions), 1)
            self.assertIs(repository.saved_result, result)

    def test_raises_clear_error_when_mineru_markdown_is_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pdf_path = root / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")
            output_dir = root / "mineru-output"
            runner = MissingMarkdownRunner(output_dir=output_dir)
            service = PDFIngestionService(
                mineru_runner=runner,
                deepseek_client=FakeDeepSeekClient(),
                repository=RecordingRepository(),
            )

            with self.assertRaises(PDFIngestionError):
                service.ingest_pdf("paper_001", pdf_path, output_dir)


class FakeMinerURunner:
    def __init__(self, markdown_path, markdown):
        self.markdown_path = markdown_path
        self.markdown = markdown
        self.calls = []

    def parse_pdf(self, pdf_path, output_dir):
        self.calls.append((pdf_path, output_dir))
        self.markdown_path.parent.mkdir(parents=True, exist_ok=True)
        self.markdown_path.write_text(self.markdown, encoding="utf-8")
        return MinerUResult(output_dir=output_dir, markdown_path=self.markdown_path)


class MissingMarkdownRunner:
    def __init__(self, output_dir):
        self.output_dir = output_dir

    def parse_pdf(self, pdf_path, output_dir):
        return MinerUResult(output_dir=self.output_dir, markdown_path=self.output_dir / "missing.md")


class RecordingRepository:
    def __init__(self):
        self.saved_result = None

    def save_processing_result(self, result):
        self.saved_result = result


if __name__ == "__main__":
    unittest.main()

