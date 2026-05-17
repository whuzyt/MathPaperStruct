"""Tests for ADR 010: Batch dry-run paper ingestion evaluation tool."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.batch_ingest_full import (
    _build_parser,
    _build_result_row,
    _classify_error,
    _classify_warning,
    _generate_report,
    count_pages,
)


class PDFPageCountTest(unittest.TestCase):
    def test_counts_pages_in_real_pdf(self):
        """count_pages returns an int for a valid PDF."""
        # Use a PDF from the beta corpus
        pdf_path = Path("data/beta/pdf/paper_0001.pdf")
        if not pdf_path.exists():
            self.skipTest("beta PDF corpus not available")
        pages = count_pages(pdf_path)
        self.assertIsNotNone(pages)
        self.assertIsInstance(pages, int)
        self.assertGreater(pages, 0)

    def test_returns_none_for_non_pdf(self):
        """count_pages returns None for a non-PDF file."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"not a pdf")
        try:
            result = count_pages(Path(f.name))
            self.assertIsNone(result)
        finally:
            Path(f.name).unlink(missing_ok=True)


class ArgumentParsingTest(unittest.TestCase):
    def test_required_pdf_dir(self):
        parser = _build_parser()
        args = parser.parse_args(["--pdf-dir", "data/beta/pdf"])
        self.assertEqual(args.pdf_dir, Path("data/beta/pdf"))

    def test_default_limit_10(self):
        parser = _build_parser()
        args = parser.parse_args(["--pdf-dir", "data/beta/pdf"])
        self.assertEqual(args.limit, 10)

    def test_custom_limit(self):
        parser = _build_parser()
        args = parser.parse_args(["--pdf-dir", "data/beta/pdf", "--limit", "5"])
        self.assertEqual(args.limit, 5)

    def test_resume_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["--pdf-dir", "data/beta/pdf", "--resume"])
        self.assertTrue(args.resume)

    def test_fail_fast_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["--pdf-dir", "data/beta/pdf", "--fail-fast"])
        self.assertTrue(args.fail_fast)

    def test_work_root_default(self):
        parser = _build_parser()
        args = parser.parse_args(["--pdf-dir", "data/beta/pdf"])
        self.assertIsNone(args.work_root)

    def test_custom_work_root(self):
        parser = _build_parser()
        args = parser.parse_args(
            ["--pdf-dir", "data/beta/pdf", "--work-root", "data/runs/my_batch"]
        )
        self.assertEqual(args.work_root, Path("data/runs/my_batch"))


class ResultRowTest(unittest.TestCase):
    def setUp(self):
        from question_bank.services.paper_orchestrator import (
            IngestionReport,
            StepResult,
        )

        self.success_report = IngestionReport(
            paper_id="paper_001",
            status="completed",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:00:30Z",
            steps=[
                StepResult(
                    name="mineru_parse", status="success",
                    started_at="", finished_at="",
                    input_count=1, output_count=1,
                ),
                StepResult(
                    name="layout_ownership", status="success",
                    started_at="", finished_at="",
                    input_count=45, output_count=23,
                ),
                StepResult(
                    name="deepseek_structure", status="success",
                    started_at="", finished_at="",
                    input_count=23, output_count=23,
                ),
            ],
            counts={"steps_total": 10, "steps_succeeded": 3,
                    "steps_warning": 0, "steps_failed": 0, "steps_skipped": 7},
            warnings=[],
            errors=[],
        )

    def test_success_row_extracts_correct_fields(self):
        entry = {
            "paper_id": "paper_001",
            "pages": 12,
            "work_dir": "/tmp/runs/paper_001",
            "report": self.success_report,
            "error": None,
        }
        row = _build_result_row(entry)
        self.assertEqual(row["paper_id"], "paper_001")
        self.assertEqual(row["pages"], 12)
        self.assertEqual(row["mineru"], "success")
        self.assertEqual(row["layout_in"], 45)
        self.assertEqual(row["layout_q"], 23)
        self.assertEqual(row["deepseek_out"], 23)
        self.assertEqual(row["warnings"], 0)
        self.assertEqual(row["errors"], 0)
        self.assertEqual(row["status"], "completed")

    def test_crash_row_shows_crash_status(self):
        entry = {
            "paper_id": "paper_002",
            "pages": "?",
            "work_dir": "/tmp/runs/paper_002",
            "report": None,
            "error": "MinerU exited with code 1",
        }
        row = _build_result_row(entry)
        self.assertEqual(row["paper_id"], "paper_002")
        self.assertEqual(row["mineru"], "CRASH")
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["errors"], 1)
        self.assertIn("MinerU", row["error_detail"])

    def test_row_with_missing_steps_uses_defaults(self):
        """If a step is missing from the report, defaults to 0 or '?'."""
        from question_bank.services.paper_orchestrator import (
            IngestionReport,
            StepResult,
        )

        report = IngestionReport(
            paper_id="paper_003",
            status="failed",
            started_at="", finished_at="",
            steps=[
                StepResult(
                    name="mineru_parse", status="failed",
                    started_at="", finished_at="",
                    error="MinerU exited with code 1",
                ),
            ],
            counts={"steps_total": 1, "steps_succeeded": 0,
                    "steps_warning": 0, "steps_failed": 1, "steps_skipped": 0},
            warnings=[],
            errors=["MinerU exited with code 1"],
        )
        entry = {
            "paper_id": "paper_003",
            "pages": 5,
            "work_dir": "/tmp/runs/paper_003",
            "report": report,
            "error": None,
        }
        row = _build_result_row(entry)
        self.assertEqual(row["mineru"], "failed")
        self.assertEqual(row["layout_in"], 0)
        self.assertEqual(row["layout_q"], 0)
        self.assertEqual(row["deepseek_out"], 0)
        self.assertEqual(row["status"], "failed")


class ReportGenerationTest(unittest.TestCase):
    def setUp(self):
        from question_bank.services.paper_orchestrator import (
            IngestionReport,
            StepResult,
        )

        self.good_report = IngestionReport(
            paper_id="paper_001",
            status="completed",
            started_at="", finished_at="",
            steps=[
                StepResult(name="mineru_parse", status="success",
                           started_at="", finished_at="",
                           input_count=1, output_count=1),
                StepResult(name="layout_ownership", status="success",
                           started_at="", finished_at="",
                           input_count=30, output_count=15),
                StepResult(name="deepseek_structure", status="success",
                           started_at="", finished_at="",
                           input_count=15, output_count=15),
            ],
            counts={"steps_total": 10, "steps_succeeded": 3,
                    "steps_warning": 0, "steps_failed": 0, "steps_skipped": 7},
            warnings=[],
            errors=[],
        )

        self.bad_report = IngestionReport(
            paper_id="paper_002",
            status="partial",
            started_at="", finished_at="",
            steps=[
                StepResult(name="mineru_parse", status="success",
                           started_at="", finished_at="",
                           input_count=1, output_count=1),
                StepResult(name="layout_ownership", status="success",
                           started_at="", finished_at="",
                           input_count=20, output_count=10),
                StepResult(name="deepseek_structure", status="success",
                           started_at="", finished_at="",
                           input_count=10, output_count=10),
                StepResult(name="crop_assets", status="warning",
                           started_at="", finished_at="",
                           input_count=5, output_count=3,
                           warnings=["2/5 crops failed"]),
            ],
            counts={"steps_total": 10, "steps_succeeded": 3,
                    "steps_warning": 1, "steps_failed": 0, "steps_skipped": 6},
            warnings=["2/5 crops failed"],
            errors=[],
        )

        self.error_results = IngestionReport(
            paper_id="paper_003",
            status="failed",
            started_at="", finished_at="",
            steps=[
                StepResult(name="mineru_parse", status="failed",
                           started_at="", finished_at="",
                           error="MinerU exited with code 1"),
            ],
            counts={"steps_total": 1, "steps_succeeded": 0,
                    "steps_warning": 0, "steps_failed": 1, "steps_skipped": 0},
            warnings=[],
            errors=["MinerU exited with code 1"],
        )

    def test_report_contains_expected_sections(self):
        results = [
            {"paper_id": "paper_001", "pages": 12, "work_dir": "/tmp/runs/p1",
             "report": self.good_report, "error": None},
            {"paper_id": "paper_002", "pages": 8, "work_dir": "/tmp/runs/p2",
             "report": self.bad_report, "error": None},
        ]
        # create a fake args for _generate_report
        args = mock.Mock(resume=False, fail_fast=False)
        content = _generate_report(results, 45.0, args)

        self.assertIn("# Batch Ingestion Evaluation", content)
        self.assertIn("## Summary", content)
        self.assertIn("## Per-Paper Results", content)
        self.assertIn("## Per-Paper Detail", content)
        self.assertIn("## Conclusion", content)
        self.assertIn("paper_001", content)
        self.assertIn("paper_002", content)
        self.assertIn("completed", content)
        self.assertIn("partial", content)

    def test_report_includes_failure_reasons_when_present(self):
        results = [
            {"paper_id": "paper_003", "pages": 3, "work_dir": "/tmp/runs/p3",
             "report": self.error_results, "error": None},
        ]
        args = mock.Mock(resume=False, fail_fast=False)
        content = _generate_report(results, 12.0, args)

        self.assertIn("## Top Failure Reasons", content)
        self.assertIn("MinerU", content)

    def test_report_includes_warning_patterns(self):
        results = [
            {"paper_id": "paper_002", "pages": 8, "work_dir": "/tmp/runs/p2",
             "report": self.bad_report, "error": None},
        ]
        args = mock.Mock(resume=False, fail_fast=False)
        content = _generate_report(results, 20.0, args)

        self.assertIn("## Top Warning Patterns", content)
        self.assertIn("Crop", content)

    def test_report_handles_crashed_entry(self):
        results = [
            {"paper_id": "paper_004", "pages": "?", "work_dir": "/tmp/runs/p4",
             "report": None, "error": "MinerU command not found"},
        ]
        args = mock.Mock(resume=False, fail_fast=False)
        content = _generate_report(results, 5.0, args)

        self.assertIn("paper_004", content)
        self.assertIn("Unhandled crash", content)
        self.assertIn("MinerU command not found", content)

    def test_passing_report_verdict(self):
        """When >= 80% completed, verdict is PASS."""
        results = [
            {"paper_id": f"paper_{i:04d}", "pages": 5,
             "work_dir": f"/tmp/runs/p{i}",
             "report": self.good_report, "error": None}
            for i in range(1, 11)
        ]
        # 10/10 completed = 100% > 80%
        args = mock.Mock(resume=False, fail_fast=False)
        content = _generate_report(results, 100.0, args)
        self.assertIn("**PASS**", content)

    def test_failing_report_verdict(self):
        """When < 80% completed, verdict is BLOCKED."""
        results = [
            {"paper_id": f"paper_{i:04d}", "pages": 3,
             "work_dir": f"/tmp/runs/p{i}",
             "report": self.error_results, "error": None}
            for i in range(1, 6)
        ]
        # 0/5 completed = 0% < 80%
        args = mock.Mock(resume=False, fail_fast=False)
        content = _generate_report(results, 25.0, args)
        self.assertIn("**BLOCKED**", content)


class ErrorClassificationTest(unittest.TestCase):
    def test_mineru_error(self):
        self.assertIn("MinerU", _classify_error("MinerU exited with code 1"))

    def test_mineru_not_found(self):
        self.assertIn("not found",
                       _classify_error("mineru: command not found"))

    def test_layout_error(self):
        self.assertIn("Layout",
                       _classify_error("layout_ownership failed: index out of range"))

    def test_deepseek_error(self):
        self.assertIn("DeepSeek",
                       _classify_error("DeepSeek API returned 500"))

    def test_database_error(self):
        self.assertIn("Database",
                       _classify_error("psycopg connection refused"))

    def test_generic_error(self):
        self.assertIn("Other", _classify_error("something unexpected happened"))

    def test_warning_crop(self):
        self.assertIn("Crop", _classify_warning("3/10 crops failed"))

    def test_warning_phash(self):
        self.assertIn("pHash", _classify_warning("phash computation failed"))

    def test_warning_visual(self):
        self.assertIn("Visual",
                       _classify_warning("visual candidate generation error"))


class BatchIntegrationTest(unittest.TestCase):
    """Integration-style tests that mock ingest_paper_full."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.pdf_dir = Path(self.tmpdir) / "pdfs"
        self.pdf_dir.mkdir()
        # Create 5 fake PDF files
        for i in range(1, 6):
            (self.pdf_dir / f"paper_{i:04d}.pdf").write_bytes(
                b"%PDF-1.4 fake pdf content"
            )

        from question_bank.services.paper_orchestrator import (
            IngestionReport,
            StepResult,
        )

        self.mock_report = IngestionReport(
            paper_id="paper", status="completed",
            started_at="", finished_at="",
            steps=[
                StepResult(name="mineru_parse", status="success",
                           started_at="", finished_at="",
                           input_count=1, output_count=1),
                StepResult(name="layout_ownership", status="success",
                           started_at="", finished_at="",
                           input_count=30, output_count=15),
                StepResult(name="deepseek_structure", status="success",
                           started_at="", finished_at="",
                           input_count=15, output_count=15),
            ],
            counts={"steps_total": 10, "steps_succeeded": 3,
                    "steps_warning": 0, "steps_failed": 0, "steps_skipped": 7},
            warnings=[],
            errors=[],
        )

    def test_discovers_pdf_files_in_directory(self):
        """The batch tool finds all PDF files in --pdf-dir."""
        from tools.batch_ingest_full import main

        with mock.patch(
            "question_bank.services.paper_orchestrator.ingest_paper_full",
            return_value=self.mock_report,
        ):
            exit_code = main([
                "--pdf-dir", str(self.pdf_dir),
                "--limit", "3",
                "--work-root", str(Path(self.tmpdir) / "runs"),
                "--asset-dir", str(Path(self.tmpdir) / "assets"),
                "--report-dir", str(Path(self.tmpdir) / "reports"),
            ])

        self.assertEqual(exit_code, 0)

    def test_limit_restricts_pdf_count(self):
        """--limit 2 processes at most 2 PDFs."""
        from tools.batch_ingest_full import main

        call_count = [0]

        def counting_ingest(*args, **kwargs):
            call_count[0] += 1
            return self.mock_report

        with mock.patch(
            "question_bank.services.paper_orchestrator.ingest_paper_full",
            side_effect=counting_ingest,
        ):
            main([
                "--pdf-dir", str(self.pdf_dir),
                "--limit", "2",
                "--work-root", str(Path(self.tmpdir) / "runs"),
                "--asset-dir", str(Path(self.tmpdir) / "assets"),
                "--report-dir", str(Path(self.tmpdir) / "reports"),
            ])

        self.assertEqual(call_count[0], 2)

    def test_failure_does_not_stop_others_by_default(self):
        """Without --fail-fast, one failure continues to next PDF."""
        from tools.batch_ingest_full import main

        call_count = [0]

        def flaky_ingest(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("MinerU crashed")
            return self.mock_report

        with mock.patch(
            "question_bank.services.paper_orchestrator.ingest_paper_full",
            side_effect=flaky_ingest,
        ):
            exit_code = main([
                "--pdf-dir", str(self.pdf_dir),
                "--limit", "3",
                "--work-root", str(Path(self.tmpdir) / "runs"),
                "--asset-dir", str(Path(self.tmpdir) / "assets"),
                "--report-dir", str(Path(self.tmpdir) / "reports"),
            ])

        # All 3 PDFs should be attempted despite one failure
        self.assertEqual(call_count[0], 3)
        # 2/3 completed = 66.7% < 80% → BLOCKED
        self.assertEqual(exit_code, 1)

    def test_fail_fast_stops_on_first_failure(self):
        """With --fail-fast, first failure stops the batch."""
        from tools.batch_ingest_full import main

        call_count = [0]

        def flaky_ingest(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("MinerU crashed")
            return self.mock_report

        with mock.patch(
            "question_bank.services.paper_orchestrator.ingest_paper_full",
            side_effect=flaky_ingest,
        ):
            exit_code = main([
                "--pdf-dir", str(self.pdf_dir),
                "--limit", "5",
                "--work-root", str(Path(self.tmpdir) / "runs"),
                "--asset-dir", str(Path(self.tmpdir) / "assets"),
                "--fail-fast",
                "--report-dir", str(Path(self.tmpdir) / "reports"),
            ])

        # Should stop after the 2nd PDF (which failed)
        self.assertEqual(call_count[0], 2)

    def test_resume_flag_is_passed_to_orchestrator(self):
        """--resume is passed as resume=True to ingest_paper_full."""
        from tools.batch_ingest_full import main

        received_resume = []

        def capture_ingest(*args, **kwargs):
            received_resume.append(kwargs.get("resume", False))
            return self.mock_report

        with mock.patch(
            "question_bank.services.paper_orchestrator.ingest_paper_full",
            side_effect=capture_ingest,
        ):
            main([
                "--pdf-dir", str(self.pdf_dir),
                "--limit", "2",
                "--work-root", str(Path(self.tmpdir) / "runs"),
                "--asset-dir", str(Path(self.tmpdir) / "assets"),
                "--resume",
                "--report-dir", str(Path(self.tmpdir) / "reports"),
            ])

        self.assertTrue(all(received_resume),
                        f"Expected resume=True, got {received_resume}")

    def test_summary_json_written(self):
        """A batch-summary-<date>.json is created in work-root."""
        from tools.batch_ingest_full import main

        work_root = Path(self.tmpdir) / "runs"
        with mock.patch(
            "question_bank.services.paper_orchestrator.ingest_paper_full",
            return_value=self.mock_report,
        ):
            main([
                "--pdf-dir", str(self.pdf_dir),
                "--limit", "2",
                "--work-root", str(work_root),
                "--asset-dir", str(Path(self.tmpdir) / "assets"),
                "--report-dir", str(Path(self.tmpdir) / "reports"),
            ])

        # Find the summary JSON
        summaries = list(work_root.glob("batch-summary-*.json"))
        self.assertEqual(len(summaries), 1)
        data = json.loads(summaries[0].read_text())
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["completed"], 2)
        self.assertIn("papers", data)
        self.assertEqual(len(data["papers"]), 2)


if __name__ == "__main__":
    unittest.main()
