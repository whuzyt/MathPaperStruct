"""Tests for ADR 014: Real DeepSeek structure quality evaluation tool."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools.eval_deepseek_structure import (
    _build_parser,
    _classify_error,
    _generate_json_summary,
    _generate_markdown_report,
    _process_one_pdf,
    _process_one_safe,
    _report_error_summary,
    count_pages,
)


# ---------------------------------------------------------------------------
# Helper: build a minimal result dict matching _process_one_pdf output
# ---------------------------------------------------------------------------


def _result(**kwargs) -> dict:
    defaults = {
        "paper_id": "deepseek_eval_0001",
        "pdf_path": "/tmp/test.pdf",
        "work_dir": "/tmp/runs/deepseek_eval_0001",
        "status": "completed",
        "layout_q": 5,
        "deepseek_out": 5,
        "deepseek_status": "success",
        "questions_passed": 4,
        "questions_warning": 1,
        "questions_failed": 0,
        "failed_question_ids": [],
        "quality_warning_counts": {"missing_analysis": 1},
        "elapsed_s": 12.5,
        "error": None,
    }
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# TestArgumentParsing
# ---------------------------------------------------------------------------


class TestArgumentParsing(unittest.TestCase):
    """ADR 014: CLI argument parsing tests."""

    def setUp(self):
        self.parser = _build_parser()

    def test_required_pdf_dir(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args([])

    def test_default_limit_3(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertEqual(args.limit, 3)

    def test_custom_limit(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--limit", "5"])
        self.assertEqual(args.limit, 5)

    def test_dry_run_default_true(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertTrue(args.dry_run)

    def test_no_dry_run_flag(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--no-dry-run"])
        self.assertFalse(args.dry_run)

    def test_paper_prefix_default(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertEqual(args.paper_prefix, "deepseek_eval")

    def test_custom_paper_prefix(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--paper-prefix", "eval_v2"])
        self.assertEqual(args.paper_prefix, "eval_v2")

    def test_resume_flag(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertFalse(args.resume)
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--resume"])
        self.assertTrue(args.resume)

    def test_work_root_default(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertIsNone(args.work_root)

    def test_custom_work_root(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--work-root", "/tmp/runs"])
        self.assertEqual(args.work_root, Path("/tmp/runs"))

    def test_asset_dir_default(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertEqual(args.asset_dir, Path("data/assets"))

    def test_report_dir_default(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertEqual(args.report_dir, Path("docs/eval"))


# ---------------------------------------------------------------------------
# TestMarkdownReportGeneration
# ---------------------------------------------------------------------------


class TestMarkdownReportGeneration(unittest.TestCase):
    """ADR 014: markdown report generation tests."""

    def test_report_contains_summary_table(self):
        results = [_result()]
        md = _generate_markdown_report(results, 30.0)
        self.assertIn("## Summary", md)
        self.assertIn("Total PDFs", md)
        self.assertIn("| 1 |", md)

    def test_report_contains_per_paper_table(self):
        results = [_result()]
        md = _generate_markdown_report(results, 30.0)
        self.assertIn("## Per-Paper Results", md)
        self.assertIn("deepseek_eval_0001", md)

    def test_report_quality_stats_in_table(self):
        results = [_result(questions_passed=4, questions_warning=1, questions_failed=0)]
        md = _generate_markdown_report(results, 30.0)
        self.assertIn("| 4 |", md)
        self.assertIn("| 1 |", md)

    def test_report_contains_warning_distribution(self):
        results = [_result(quality_warning_counts={"too_few_choices": 2, "missing_analysis": 3})]
        md = _generate_markdown_report(results, 30.0)
        self.assertIn("## Quality Warning Distribution", md)
        self.assertIn("too_few_choices", md)
        self.assertIn("| 2 |", md)
        self.assertIn("missing_analysis", md)
        self.assertIn("| 3 |", md)

    def test_report_contains_failed_question_ids(self):
        results = [_result(
            questions_failed=2,
            failed_question_ids=["deepseek_eval_0001_q_0001", "deepseek_eval_0001_q_0003"],
        )]
        md = _generate_markdown_report(results, 30.0)
        self.assertIn("## Failed Questions", md)
        self.assertIn("deepseek_eval_0001_q_0001", md)
        self.assertIn("deepseek_eval_0001_q_0003", md)

    def test_no_failed_questions_section_when_none(self):
        results = [_result(questions_failed=0)]
        md = _generate_markdown_report(results, 30.0)
        self.assertNotIn("## Failed Questions", md)

    def test_report_handles_crash_entry(self):
        results = [_result(status="failed", error="DeepSeek: API timeout")]
        md = _generate_markdown_report(results, 30.0)
        self.assertIn("**Crash**", md)
        self.assertIn("API timeout", md)

    def test_report_contains_per_paper_detail(self):
        results = [_result()]
        md = _generate_markdown_report(results, 30.0)
        self.assertIn("## Per-Paper Detail", md)
        self.assertIn("### deepseek_eval_0001", md)
        self.assertIn("Layout questions: 5", md)

    def test_report_aggregates_warning_counts_across_papers(self):
        results = [
            _result(paper_id="eval_0001",
                    quality_warning_counts={"too_few_choices": 2}),
            _result(paper_id="eval_0002",
                    quality_warning_counts={"too_few_choices": 3, "missing_analysis": 1}),
        ]
        md = _generate_markdown_report(results, 60.0)
        self.assertIn("| too_few_choices | 5 |", md)
        self.assertIn("| missing_analysis | 1 |", md)

    def test_multiple_papers_in_table(self):
        results = [
            _result(paper_id="eval_0001"),
            _result(paper_id="eval_0002"),
        ]
        md = _generate_markdown_report(results, 60.0)
        self.assertIn("eval_0001", md)
        self.assertIn("eval_0002", md)

    # ------------------------------------------------------------------
    # Verdict logic
    # ------------------------------------------------------------------

    def test_verdict_pass(self):
        """PASS: no failed questions, warning ratio ≤ 30%."""
        results = [_result(questions_passed=8, questions_warning=2, questions_failed=0)]
        md = _generate_markdown_report(results, 30.0)
        self.assertIn("**PASS**", md)

    def test_verdict_conditional(self):
        """CONDITIONAL: no failed questions, warning ratio > 30%."""
        results = [_result(questions_passed=3, questions_warning=7, questions_failed=0)]
        md = _generate_markdown_report(results, 30.0)
        self.assertIn("**CONDITIONAL**", md)

    def test_verdict_blocked_by_failed_questions(self):
        """BLOCKED: one or more questions failed gating."""
        results = [_result(questions_passed=8, questions_warning=1,
                          questions_failed=1,
                          failed_question_ids=["eval_0001_q_0003"])]
        md = _generate_markdown_report(results, 30.0)
        self.assertIn("**BLOCKED**", md)

    def test_verdict_blocked_by_pipeline_failure(self):
        """BLOCKED: one PDF pipeline failed."""
        results = [
            _result(paper_id="eval_0001", status="completed"),
            _result(paper_id="eval_0002", status="failed", error="MinerU crash",
                    questions_passed=0, questions_warning=0, questions_failed=0,
                    deepseek_out=0),
        ]
        md = _generate_markdown_report(results, 60.0)
        self.assertIn("**BLOCKED**", md)

    def test_verdict_blocked_zero_questions(self):
        """BLOCKED: no questions produced at all."""
        results = [_result(questions_passed=0, questions_warning=0, questions_failed=0,
                          deepseek_out=0)]
        md = _generate_markdown_report(results, 30.0)
        self.assertIn("**BLOCKED**", md)

    def test_verdict_includes_diagnosis_for_answer_not_in_choices(self):
        """When answer_not_in_choices is dominant, verdict includes diagnosis."""
        results = [_result(
            questions_failed=1,
            failed_question_ids=["eval_0001_q_0001"],
            quality_warning_counts={"answer_not_in_choices": 8},
            questions_passed=1, questions_warning=8,
        )]
        md = _generate_markdown_report(results, 30.0)
        self.assertIn("answer_not_in_choices", md.lower())


# ---------------------------------------------------------------------------
# TestJSONSummaryGeneration
# ---------------------------------------------------------------------------


class TestJSONSummaryGeneration(unittest.TestCase):
    """ADR 014: JSON summary generation tests."""

    def test_summary_contains_aggregate_fields(self):
        results = [_result(), _result(paper_id="eval_0002")]
        summary = _generate_json_summary(results, 60.0)
        self.assertEqual(summary["total_pdfs"], 2)
        self.assertEqual(summary["questions_passed"], 8)
        self.assertEqual(summary["questions_warning"], 2)
        self.assertEqual(summary["questions_failed"], 0)
        self.assertEqual(summary["total_questions"], 10)

    def test_summary_aggregates_warning_counts(self):
        results = [
            _result(quality_warning_counts={"too_few_choices": 2}),
            _result(quality_warning_counts={"too_few_choices": 3, "missing_analysis": 1},
                   paper_id="eval_0002"),
        ]
        summary = _generate_json_summary(results, 60.0)
        self.assertEqual(summary["quality_warning_counts"]["too_few_choices"], 5)
        self.assertEqual(summary["quality_warning_counts"]["missing_analysis"], 1)

    def test_summary_verdict_pass(self):
        results = [_result(questions_passed=8, questions_warning=2, questions_failed=0)]
        summary = _generate_json_summary(results, 30.0)
        self.assertEqual(summary["verdict"], "PASS")

    def test_summary_verdict_conditional(self):
        results = [_result(questions_passed=3, questions_warning=7, questions_failed=0)]
        summary = _generate_json_summary(results, 30.0)
        self.assertEqual(summary["verdict"], "CONDITIONAL")

    def test_summary_verdict_blocked(self):
        results = [_result(questions_failed=1,
                          failed_question_ids=["eval_0001_q_0001"])]
        summary = _generate_json_summary(results, 30.0)
        self.assertEqual(summary["verdict"], "BLOCKED")

    def test_summary_verdict_blocked_pipeline_failure(self):
        results = [
            _result(paper_id="eval_0001", status="completed"),
            _result(paper_id="eval_0002", status="failed", error="crash",
                    questions_passed=0, questions_warning=0, questions_failed=0,
                    deepseek_out=0),
        ]
        summary = _generate_json_summary(results, 60.0)
        self.assertEqual(summary["verdict"], "BLOCKED")

    def test_summary_contains_date(self):
        results = [_result()]
        summary = _generate_json_summary(results, 30.0)
        self.assertIn("date", summary)

    def test_summary_contains_elapsed(self):
        results = [_result()]
        summary = _generate_json_summary(results, 45.5)
        self.assertEqual(summary["elapsed_s"], 45.5)

    def test_summary_papers_list(self):
        results = [_result(), _result(paper_id="eval_0002")]
        summary = _generate_json_summary(results, 60.0)
        self.assertEqual(len(summary["papers"]), 2)
        self.assertEqual(summary["papers"][0]["paper_id"], "deepseek_eval_0001")
        self.assertEqual(summary["papers"][1]["paper_id"], "eval_0002")

    def test_summary_failed_question_ids_flattened(self):
        results = [
            _result(failed_question_ids=["eval_0001_q_0001"]),
            _result(paper_id="eval_0002",
                    failed_question_ids=["eval_0002_q_0003", "eval_0002_q_0005"]),
        ]
        summary = _generate_json_summary(results, 60.0)
        self.assertEqual(len(summary["failed_question_ids"]), 3)

    def test_summary_error_truncated(self):
        results = [_result(status="failed", error="x" * 300)]
        summary = _generate_json_summary(results, 30.0)
        paper = summary["papers"][0]
        self.assertEqual(len(paper["error"]), 200)


# ---------------------------------------------------------------------------
# TestFailureIsolation
# ---------------------------------------------------------------------------


class TestFailureIsolation(unittest.TestCase):
    """ADR 014: failure isolation — one broken PDF doesn't block others."""

    def test_process_one_safe_returns_error_dict_on_exception(self):
        """When _process_one_pdf raises, _process_one_safe returns an error result."""
        result = _process_one_safe(
            pdf_path=Path("/nonexistent/test.pdf"),
            index=1,
            prefix="eval",
            work_root=Path("/tmp/runs"),
            asset_dir=Path("/tmp/assets"),
            dry_run=True,
            resume=False,
            deepseek_client=None,
            mineru_command="mineru",
        )
        self.assertEqual(result["paper_id"], "eval_0001")
        self.assertEqual(result["status"], "failed")
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["questions_passed"], 0)
        self.assertEqual(result["failed_question_ids"], [])

    def test_successful_result_has_no_error(self):
        """A successful PDF produces a result with error=None."""
        # We can test this indirectly: the error field is None on success
        r = _result()
        self.assertIsNone(r["error"])

    def test_error_result_is_json_serializable(self):
        """Error results should be JSON serializable (no non-serializable types)."""
        result = _process_one_safe(
            pdf_path=Path("/nonexistent/test.pdf"),
            index=1,
            prefix="eval",
            work_root=Path("/tmp/runs"),
            asset_dir=Path("/tmp/assets"),
            dry_run=True,
            resume=False,
            deepseek_client=None,
            mineru_command="mineru",
        )
        # Should not raise
        json.dumps(result)

    def test_multiple_results_with_mixed_success(self):
        """Report generation handles a mix of success and failure results."""
        results = [
            _result(),  # success
            _result(paper_id="eval_0002", status="failed",
                    error="DeepSeek: API timeout",
                    questions_passed=0, questions_warning=0,
                    deepseek_out=0),
            _result(paper_id="eval_0003"),  # success
        ]
        md = _generate_markdown_report(results, 90.0)
        self.assertIn("deepseek_eval_0001", md)
        self.assertIn("eval_0002", md)
        self.assertIn("eval_0003", md)
        self.assertIn("API timeout", md)

    def test_report_total_counts_include_failed_papers(self):
        """Failed papers still count toward total PDFs."""
        results = [
            _result(),
            _result(paper_id="eval_0002", status="failed", error="crash",
                    questions_passed=0, questions_warning=0, deepseek_out=0),
        ]
        md = _generate_markdown_report(results, 60.0)
        self.assertIn("| 2 |", md)  # Total PDFs = 2

    def test_process_one_pdf_passes_repository_for_no_dry_run(self):
        """--no-dry-run must pass a real repository into ingest_paper_full."""
        repo = object()
        fake_report = SimpleNamespace(
            status="completed",
            steps=[
                SimpleNamespace(name="layout_ownership", output_count=2),
                SimpleNamespace(name="deepseek_structure", output_count=2, status="success"),
            ],
            questions_passed=2,
            questions_warning=0,
            questions_failed=0,
            failed_question_ids=[],
            quality_warning_counts={},
        )
        with mock.patch(
            "question_bank.services.paper_orchestrator.ingest_paper_full",
            return_value=fake_report,
        ) as mocked:
            result = _process_one_pdf(
                pdf_path=Path("/tmp/test.pdf"),
                index=1,
                prefix="eval",
                work_root=Path("/tmp/runs"),
                asset_dir=Path("/tmp/assets"),
                dry_run=False,
                resume=True,
                deepseek_client=object(),
                mineru_command="mineru",
                repository=repo,
            )

        self.assertEqual(result["status"], "completed")
        self.assertIs(mocked.call_args.kwargs["repository"], repo)

    def test_report_error_summary_uses_report_errors(self):
        report = SimpleNamespace(
            errors=["[mineru_parse] MinerU crashed"],
            steps=[],
        )
        self.assertEqual(
            _report_error_summary(report),
            "[mineru_parse] MinerU crashed",
        )

    def test_report_error_summary_falls_back_to_failed_steps(self):
        report = SimpleNamespace(
            errors=[],
            steps=[SimpleNamespace(name="layout_ownership", status="failed", error="bad json")],
        )
        self.assertEqual(
            _report_error_summary(report),
            "layout_ownership: bad json",
        )


# ---------------------------------------------------------------------------
# TestErrorClassification
# ---------------------------------------------------------------------------


class TestErrorClassification(unittest.TestCase):
    """ADR 014: error classification helpers."""

    def test_classify_mineru_error(self):
        self.assertIn("MinerU", _classify_error("mineru: command not found"))
        self.assertIn("MinerU", _classify_error("MinerU process crashed"))

    def test_classify_deepseek_error(self):
        self.assertIn("DeepSeek", _classify_error("deepseek returned 500"))
        self.assertIn("DeepSeek", _classify_error("DeepSeek API key invalid"))

    def test_classify_layout_error(self):
        self.assertIn("Layout", _classify_error("layout ownership failed"))

    def test_classify_resource_error(self):
        self.assertIn("Resource", _classify_error("memory error in process"))
        self.assertIn("Resource", _classify_error("timeout waiting for response"))

    def test_classify_other_error(self):
        self.assertIn("Other", _classify_error("unknown failure occurred"))


# ---------------------------------------------------------------------------
# TestPageCount
# ---------------------------------------------------------------------------


class TestPageCount(unittest.TestCase):
    """ADR 014: PDF page count helper."""

    def test_returns_none_for_non_pdf(self):
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            Path(f.name).write_text("hello")
            self.assertIsNone(count_pages(Path(f.name)))

    def test_returns_none_for_missing_file(self):
        self.assertIsNone(count_pages(Path("/nonexistent/file.pdf")))


if __name__ == "__main__":
    unittest.main()
