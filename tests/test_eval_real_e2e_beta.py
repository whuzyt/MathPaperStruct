"""Tests for ADR 020/021: Small-Scale Real Ingestion Beta evaluation tool."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools.eval_real_e2e_beta import (
    _build_parser,
    _generate_json_summary,
    _generate_markdown_report,
    _process_one_pdf,
    _process_one_safe,
    _report_error_summary,
    _summarize_from_existing,
)


# ---------------------------------------------------------------------------
# Helper: build a minimal result dict matching _process_one_pdf output
# ---------------------------------------------------------------------------


def _result(**kwargs) -> dict:
    defaults = {
        "paper_id": "real_beta_2026_05_19_0001",
        "pdf_path": "/tmp/test.pdf",
        "work_dir": "/tmp/runs/real_beta_2026_05_19_0001",
        "status": "completed",
        "pages": 10,
        "layout_q": 21,
        "deepseek_out": 21,
        "questions_passed": 20,
        "questions_warning": 1,
        "questions_failed": 0,
        "failed_question_ids": [],
        "quality_warning_counts": {"too_few_choices": 1},
        "raw_assets": 2,
        "qa_links": 2,
        "unlinked_raw_assets": 0,
        "links_without_question_block": 0,
        "crop_success": 2,
        "crop_failed": 0,
        "phash_success": 2,
        "duplicate_candidates": 3,
        "visual_candidates": 1,
        "elapsed_s": 45.5,
        "retry_count": 0,
        "previous_error": None,
        "error": None,
    }
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# TestArgumentParsing
# ---------------------------------------------------------------------------


class TestArgumentParsing(unittest.TestCase):
    """ADR 020: CLI argument parsing tests."""

    def setUp(self):
        self.parser = _build_parser()

    def test_required_pdf_dir(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args([])

    def test_default_limit_20(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertEqual(args.limit, 20)

    def test_custom_limit(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--limit", "10"])
        self.assertEqual(args.limit, 10)

    def test_default_paper_prefix(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertEqual(args.paper_prefix, "real_beta_2026_05_19")

    def test_custom_paper_prefix(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--paper-prefix", "beta_v2"])
        self.assertEqual(args.paper_prefix, "beta_v2")

    def test_resume_flag_default_false(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertFalse(args.resume)

    def test_resume_flag(self):
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
    """ADR 020: markdown report generation tests."""

    def test_report_contains_summary_table(self):
        results = [_result()]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("## Summary", md)
        self.assertIn("Total PDFs", md)
        self.assertIn("| 1 |", md)

    def test_report_contains_success_rate(self):
        results = [_result(), _result(paper_id="beta_0002", status="partial")]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("Success rate (completed + partial)", md)
        self.assertIn("100.0%", md)

    def test_report_contains_asset_pipeline_summary(self):
        results = [_result(raw_assets=2, qa_links=2, crop_success=2, crop_failed=0, phash_success=2)]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("## Asset Pipeline Summary", md)
        self.assertIn("Total raw_assets", md)
        self.assertIn("| 2 |", md)
        self.assertIn("Crop success rate", md)

    def test_report_contains_per_paper_table_with_asset_columns(self):
        results = [_result()]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("## Per-Paper Results", md)
        self.assertIn("Assets", md)
        self.assertIn("Links", md)
        self.assertIn("CropOK", md)
        self.assertIn("CropFail", md)
        self.assertIn("pHash", md)
        self.assertIn("Dup", md)
        self.assertIn("Vis", md)
        self.assertIn("real_beta_2026_05_19_0001", md)

    def test_report_quality_stats_in_table(self):
        results = [_result(questions_passed=20, questions_warning=1, questions_failed=0)]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("| 20 |", md)
        self.assertIn("| 1 |", md)

    def test_report_contains_warning_distribution(self):
        results = [_result(quality_warning_counts={"too_few_choices": 2, "missing_analysis": 3})]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("## Quality Warning Distribution", md)
        self.assertIn("too_few_choices", md)
        self.assertIn("missing_analysis", md)

    def test_report_contains_failed_question_ids(self):
        results = [_result(
            questions_failed=2,
            failed_question_ids=["beta_0001_q_0001", "beta_0001_q_0003"],
        )]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("## Failed Questions", md)
        self.assertIn("beta_0001_q_0001", md)

    def test_no_failed_questions_section_when_none(self):
        results = [_result(questions_failed=0)]
        md = _generate_markdown_report(results, 120.0)
        self.assertNotIn("## Failed Questions", md)

    def test_report_handles_crash_entry(self):
        results = [_result(status="failed", error="DeepSeek: API timeout")]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("## Pipeline Errors", md)
        self.assertIn("API timeout", md)

    def test_report_aggregates_warning_counts_across_papers(self):
        results = [
            _result(quality_warning_counts={"too_few_choices": 2}),
            _result(paper_id="beta_0002",
                    quality_warning_counts={"too_few_choices": 3, "missing_analysis": 1}),
        ]
        md = _generate_markdown_report(results, 240.0)
        self.assertIn("| too_few_choices | 5 |", md)
        self.assertIn("| missing_analysis | 1 |", md)

    def test_multiple_papers_in_table(self):
        results = [
            _result(),
            _result(paper_id="beta_0002"),
        ]
        md = _generate_markdown_report(results, 240.0)
        self.assertIn("real_beta_2026_05_19_0001", md)
        self.assertIn("beta_0002", md)

    def test_pages_column_shown(self):
        results = [_result(pages=12)]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("| 12 |", md)

    def test_pages_none_shown_as_question_mark(self):
        results = [_result(pages=None)]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("| ? |", md)

    def test_asset_columns_in_per_paper_table(self):
        results = [_result(raw_assets=3, qa_links=3, crop_success=3, crop_failed=1,
                          phash_success=3, duplicate_candidates=5, visual_candidates=2)]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("| 3 | 3 | 3 | 1 | 3 | 5 | 2 | completed |", md)

    # ------------------------------------------------------------------
    # Verdict / acceptance gates
    # ------------------------------------------------------------------

    def test_verdict_pass_all_gates(self):
        """PASS: all 7 acceptance gates met with 20 PDFs."""
        results = []
        for i in range(20):
            results.append(_result(
                paper_id=f"beta_{i:04d}",
                questions_passed=20, questions_warning=1, questions_failed=0,
                raw_assets=2, crop_success=2, crop_failed=0, phash_success=2,
            ))
        md = _generate_markdown_report(results, 1000.0)
        self.assertIn("**PASS**", md)
        self.assertNotIn("**BLOCKED**", md)

    def test_verdict_blocked_by_pipeline_failures(self):
        """BLOCKED: pipeline_failed > 0."""
        results = [
            _result(),
            _result(paper_id="beta_0002", status="failed", error="crash",
                    questions_passed=0, questions_warning=0,
                    raw_assets=0, crop_success=0, phash_success=0),
        ]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("**BLOCKED**", md)

    def test_verdict_blocked_by_failed_questions(self):
        """BLOCKED: questions_failed > 0."""
        results = [_result(questions_failed=1, failed_question_ids=["beta_0001_q_0003"])]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("**BLOCKED**", md)

    def test_verdict_blocked_by_warning_rate(self):
        """BLOCKED: warning rate > 10%."""
        results = [_result(questions_passed=5, questions_warning=10, questions_failed=0)]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("**BLOCKED**", md)

    def test_verdict_blocked_by_low_success_rate(self):
        """BLOCKED: completed+partial < 90%."""
        # 2 of 10 pass = 20% < 90%
        results = []
        for i in range(10):
            status = "completed" if i < 2 else "failed"
            results.append(_result(
                paper_id=f"beta_{i:04d}", status=status,
                questions_passed=0 if status == "failed" else 20,
                raw_assets=0, crop_success=0, phash_success=0,
            ))
        md = _generate_markdown_report(results, 500.0)
        self.assertIn("**BLOCKED**", md)

    def test_verdict_blocked_by_low_crop_rate(self):
        """BLOCKED: crop success < 80%."""
        results = [_result(crop_success=1, crop_failed=5, phash_success=1)]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("**BLOCKED**", md)

    def test_verdict_blocked_by_low_phash_rate(self):
        """BLOCKED: pHash success < 80%."""
        results = [_result(crop_success=10, crop_failed=0, phash_success=2)]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("**BLOCKED**", md)

    def test_verdict_blocked_by_few_pdfs_with_assets(self):
        """BLOCKED: raw_assets on < 50% PDFs."""
        results = []
        for i in range(10):
            has_assets = i < 2  # only 2 of 10 = 20%
            results.append(_result(
                paper_id=f"beta_{i:04d}",
                raw_assets=2 if has_assets else 0,
                crop_success=2 if has_assets else 0,
                phash_success=2 if has_assets else 0,
            ))
        md = _generate_markdown_report(results, 500.0)
        self.assertIn("**BLOCKED**", md)

    def test_acceptance_gates_table(self):
        results = [_result()]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("### Acceptance Gates", md)
        self.assertIn("Completed + partial ≥ 90%", md)
        self.assertIn("Pipeline failed = 0", md)
        self.assertIn("Questions failed = 0", md)
        self.assertIn("Warning rate ≤ 10%", md)
        self.assertIn("raw_assets > 0 on ≥ 50% PDFs", md)
        self.assertIn("question_asset_links > 0", md)
        self.assertIn("Unlinked raw_assets ≤ 10%", md)
        self.assertIn("Links without question_block = 0", md)
        self.assertIn("Crop success ≥ 80%", md)
        self.assertIn("pHash success ≥ 80%", md)

    def test_gates_all_show_pass_for_clean_result(self):
        results = [_result()]
        md = _generate_markdown_report(results, 120.0)
        # 10 gates should all PASS
        self.assertEqual(md.count("**PASS**"), 10 + 1)  # 10 gate rows + 1 verdict

    def test_crop_rate_n_a_when_no_assets(self):
        """When there are no assets, crop rate should show N/A."""
        results = [_result(raw_assets=0, crop_success=0, crop_failed=0, phash_success=0)]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("N/A", md)

    def test_no_pipeline_errors_section_when_none(self):
        results = [_result()]
        md = _generate_markdown_report(results, 120.0)
        self.assertNotIn("## Pipeline Errors", md)

    def test_qa_links_negative_handled(self):
        """qa_links = -1 (DB error) should not break report."""
        results = [_result(qa_links=-1)]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("real_beta_2026_05_19_0001", md)

    def test_verdict_blocked_by_zero_links(self):
        results = [_result(qa_links=0)]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("**BLOCKED**", md)

    def test_verdict_blocked_by_unlinked_assets(self):
        results = [_result(raw_assets=10, qa_links=8, unlinked_raw_assets=2)]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("**BLOCKED**", md)

    def test_verdict_blocked_by_links_without_question_block(self):
        results = [_result(links_without_question_block=1)]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("**BLOCKED**", md)


# ---------------------------------------------------------------------------
# TestJSONSummaryGeneration
# ---------------------------------------------------------------------------


class TestJSONSummaryGeneration(unittest.TestCase):
    """ADR 020: JSON summary generation tests."""

    def test_summary_contains_aggregate_fields(self):
        results = [_result(), _result(paper_id="beta_0002")]
        summary = _generate_json_summary(results, 240.0)
        self.assertEqual(summary["total_pdfs"], 2)
        self.assertEqual(summary["questions_passed"], 40)
        self.assertEqual(summary["questions_warning"], 2)
        self.assertEqual(summary["questions_failed"], 0)
        self.assertEqual(summary["total_questions"], 42)

    def test_summary_contains_asset_fields(self):
        results = [_result()]
        summary = _generate_json_summary(results, 120.0)
        self.assertEqual(summary["total_raw_assets"], 2)
        self.assertEqual(summary["total_question_asset_links"], 2)
        self.assertEqual(summary["unlinked_raw_assets"], 0)
        self.assertEqual(summary["links_without_question_block"], 0)
        self.assertEqual(summary["crop_success"], 2)
        self.assertEqual(summary["crop_failed"], 0)
        self.assertEqual(summary["phash_computed"], 2)
        self.assertEqual(summary["duplicate_candidate_groups"], 3)
        self.assertEqual(summary["visual_candidate_groups"], 1)

    def test_summary_aggregates_warning_counts(self):
        results = [
            _result(quality_warning_counts={"too_few_choices": 2}),
            _result(paper_id="beta_0002",
                    quality_warning_counts={"too_few_choices": 3, "missing_analysis": 1}),
        ]
        summary = _generate_json_summary(results, 240.0)
        self.assertEqual(summary["quality_warning_counts"]["too_few_choices"], 5)
        self.assertEqual(summary["quality_warning_counts"]["missing_analysis"], 1)

    def test_summary_verdict_pass(self):
        results = [_result()]
        summary = _generate_json_summary(results, 120.0)
        self.assertEqual(summary["verdict"], "PASS")

    def test_summary_verdict_blocked(self):
        results = [_result(questions_failed=1, failed_question_ids=["beta_0001_q_0001"])]
        summary = _generate_json_summary(results, 120.0)
        self.assertEqual(summary["verdict"], "BLOCKED")

    def test_summary_verdict_blocked_by_warning_rate(self):
        results = [_result(questions_passed=5, questions_warning=10, questions_failed=0)]
        summary = _generate_json_summary(results, 120.0)
        self.assertEqual(summary["verdict"], "BLOCKED")

    def test_summary_verdict_blocked_by_success_rate(self):
        results = []
        for i in range(10):
            status = "completed" if i < 2 else "failed"
            results.append(_result(
                paper_id=f"beta_{i:04d}", status=status,
                questions_passed=0 if status == "failed" else 20,
                raw_assets=0, crop_success=0, phash_success=0,
            ))
        summary = _generate_json_summary(results, 500.0)
        self.assertEqual(summary["verdict"], "BLOCKED")

    def test_summary_gates_structure(self):
        results = [_result()]
        summary = _generate_json_summary(results, 120.0)
        self.assertIn("gates", summary)
        gates = summary["gates"]
        self.assertIn("success_rate_90pct", gates)
        self.assertIn("pipeline_failed_0", gates)
        self.assertIn("questions_failed_0", gates)
        self.assertIn("warning_rate_10pct", gates)
        self.assertIn("pdfs_with_assets_50pct", gates)
        self.assertIn("question_asset_links_gt_0", gates)
        self.assertIn("unlinked_raw_assets_10pct", gates)
        self.assertIn("links_without_question_block_0", gates)
        self.assertIn("crop_success_80pct", gates)
        self.assertIn("phash_success_80pct", gates)
        for gate in gates.values():
            self.assertIn("passed", gate)
            self.assertIn("threshold", gate)
            self.assertIn("actual", gate)

    def test_summary_contains_date(self):
        results = [_result()]
        summary = _generate_json_summary(results, 120.0)
        self.assertIn("date", summary)

    def test_summary_contains_elapsed(self):
        results = [_result()]
        summary = _generate_json_summary(results, 45.5)
        self.assertEqual(summary["elapsed_s"], 45.5)

    def test_summary_papers_list(self):
        results = [_result(), _result(paper_id="beta_0002")]
        summary = _generate_json_summary(results, 240.0)
        self.assertEqual(len(summary["papers"]), 2)
        self.assertEqual(summary["papers"][0]["paper_id"], "real_beta_2026_05_19_0001")
        self.assertEqual(summary["papers"][1]["paper_id"], "beta_0002")

    def test_summary_papers_include_asset_fields(self):
        results = [_result()]
        summary = _generate_json_summary(results, 120.0)
        paper = summary["papers"][0]
        self.assertEqual(paper["raw_assets"], 2)
        self.assertEqual(paper["qa_links"], 2)
        self.assertEqual(paper["unlinked_raw_assets"], 0)
        self.assertEqual(paper["links_without_question_block"], 0)
        self.assertEqual(paper["crop_success"], 2)
        self.assertEqual(paper["crop_failed"], 0)
        self.assertEqual(paper["phash_success"], 2)
        self.assertEqual(paper["duplicate_candidates"], 3)
        self.assertEqual(paper["visual_candidates"], 1)

    def test_summary_failed_question_ids_flattened(self):
        results = [
            _result(failed_question_ids=["beta_0001_q_0001"]),
            _result(paper_id="beta_0002",
                    failed_question_ids=["beta_0002_q_0003", "beta_0002_q_0005"]),
        ]
        summary = _generate_json_summary(results, 240.0)
        self.assertEqual(len(summary["failed_question_ids"]), 3)

    def test_summary_error_truncated(self):
        results = [_result(status="failed", error="x" * 300)]
        summary = _generate_json_summary(results, 120.0)
        paper = summary["papers"][0]
        self.assertEqual(len(paper["error"]), 200)

    def test_summary_success_rate_field(self):
        results = [_result(), _result(paper_id="beta_0002", status="failed")]
        summary = _generate_json_summary(results, 240.0)
        self.assertEqual(summary["success_rate"], 50.0)

    def test_summary_pdfs_with_assets(self):
        results = [
            _result(raw_assets=2),
            _result(paper_id="beta_0002", raw_assets=0, crop_success=0, phash_success=0),
        ]
        summary = _generate_json_summary(results, 240.0)
        self.assertEqual(summary["pdfs_with_assets"], 1)


# ---------------------------------------------------------------------------
# TestFailureIsolation
# ---------------------------------------------------------------------------


class TestFailureIsolation(unittest.TestCase):
    """ADR 020: failure isolation — one broken PDF doesn't block others."""

    def test_process_one_safe_returns_error_dict_on_exception(self):
        result = _process_one_safe(
            pdf_path=Path("/nonexistent/test.pdf"),
            index=1,
            prefix="beta",
            work_root=Path("/tmp/runs"),
            asset_dir=Path("/tmp/assets"),
            resume=False,
            deepseek_client=None,
            mineru_command="mineru",
            repository=None,
        )
        self.assertEqual(result["paper_id"], "beta_0001")
        self.assertEqual(result["status"], "failed")
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["questions_passed"], 0)
        self.assertEqual(result["failed_question_ids"], [])
        self.assertEqual(result["raw_assets"], 0)
        self.assertEqual(result["crop_success"], 0)

    def test_error_result_is_json_serializable(self):
        result = _process_one_safe(
            pdf_path=Path("/nonexistent/test.pdf"),
            index=1,
            prefix="beta",
            work_root=Path("/tmp/runs"),
            asset_dir=Path("/tmp/assets"),
            resume=False,
            deepseek_client=None,
            mineru_command="mineru",
            repository=None,
        )
        json.dumps(result)

    def test_multiple_results_with_mixed_success(self):
        results = [
            _result(),
            _result(paper_id="beta_0002", status="failed", error="DeepSeek: API timeout",
                    questions_passed=0, questions_warning=0, deepseek_out=0,
                    raw_assets=0, crop_success=0, phash_success=0),
            _result(paper_id="beta_0003"),
        ]
        md = _generate_markdown_report(results, 270.0)
        self.assertIn("real_beta_2026_05_19_0001", md)
        self.assertIn("beta_0002", md)
        self.assertIn("beta_0003", md)
        self.assertIn("API timeout", md)

    def test_report_total_counts_include_failed_papers(self):
        results = [
            _result(),
            _result(paper_id="beta_0002", status="failed", error="crash",
                    questions_passed=0, questions_warning=0, deepseek_out=0,
                    raw_assets=0, crop_success=0, phash_success=0),
        ]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("| 2 |", md)

    def test_process_one_pdf_extracts_step_data(self):
        """Verify step-level data extraction from IngestionReport."""
        fake_steps = [
            SimpleNamespace(name="layout_ownership", status="success", output_count=21, warnings=[]),
            SimpleNamespace(name="deepseek_structure", status="success", output_count=21, warnings=[]),
            SimpleNamespace(name="identify_assets", status="success", output_count=3, warnings=[]),
            SimpleNamespace(name="crop_assets", status="success", output_count=3, warnings=[]),
            SimpleNamespace(name="compute_phash", status="success", output_count=3, warnings=[]),
            SimpleNamespace(name="duplicate_candidates", status="success", output_count=5, warnings=[]),
            SimpleNamespace(name="visual_candidates", status="success", output_count=2, warnings=[]),
        ]
        fake_report = SimpleNamespace(
            paper_id="beta_0001",
            status="completed",
            steps=fake_steps,
            counts={},
            warnings=[],
            errors=[],
            questions_passed=21,
            questions_warning=0,
            questions_failed=0,
            failed_question_ids=[],
            quality_warning_counts={},
        )

        with mock.patch(
            "question_bank.services.paper_orchestrator.ingest_paper_full",
            return_value=fake_report,
        ):
            repo = mock.Mock()
            cursor = mock.Mock()
            cursor.fetchone.return_value = (4,)
            repo.connection.cursor.return_value = cursor

            result = _process_one_pdf(
                pdf_path=Path("/tmp/test.pdf"),
                index=1,
                prefix="beta",
                work_root=Path("/tmp/runs"),
                asset_dir=Path("/tmp/assets"),
                resume=False,
                deepseek_client=object(),
                mineru_command="mineru",
                repository=repo,
            )

        self.assertEqual(result["layout_q"], 21)
        self.assertEqual(result["raw_assets"], 3)
        self.assertEqual(result["crop_success"], 3)
        self.assertEqual(result["phash_success"], 3)
        self.assertEqual(result["duplicate_candidates"], 5)
        self.assertEqual(result["visual_candidates"], 2)
        self.assertEqual(result["qa_links"], 4)

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

    def test_crop_warnings_detected_as_failed(self):
        """crop_assets warnings are counted as failed crops."""
        fake_steps = [
            SimpleNamespace(name="crop_assets", status="warning", output_count=2,
                          warnings=["img1: crop error", "img2: bad bbox"]),
        ]
        fake_report = SimpleNamespace(
            status="partial",
            steps=fake_steps,
            errors=[],
            questions_passed=0,
            questions_warning=0,
            questions_failed=0,
            failed_question_ids=[],
            quality_warning_counts={},
        )
        with mock.patch(
            "question_bank.services.paper_orchestrator.ingest_paper_full",
            return_value=fake_report,
        ):
            repo = mock.Mock()
            cursor = mock.Mock()
            cursor.fetchone.return_value = (0,)
            repo.connection.cursor.return_value = cursor

            result = _process_one_pdf(
                pdf_path=Path("/tmp/test.pdf"),
                index=1,
                prefix="beta",
                work_root=Path("/tmp/runs"),
                asset_dir=Path("/tmp/assets"),
                resume=False,
                deepseek_client=object(),
                mineru_command="mineru",
                repository=repo,
            )

        self.assertEqual(result["crop_success"], 2)
        self.assertEqual(result["crop_failed"], 2)


# ---------------------------------------------------------------------------
# ADR 021: Argument parsing additions
# ---------------------------------------------------------------------------


class TestADR021ArgumentParsing(unittest.TestCase):
    """ADR 021: new CLI flags."""

    def setUp(self):
        self.parser = _build_parser()

    def test_summarize_existing_flag(self):
        args = self.parser.parse_args(["--summarize-existing", "--work-root", "/tmp/runs"])
        self.assertTrue(args.summarize_existing)

    def test_summarize_existing_default_false(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertFalse(args.summarize_existing)

    def test_only_index_flag(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--only-index", "12"])
        self.assertEqual(args.only_index, 12)

    def test_only_index_default_none(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertIsNone(args.only_index)

    def test_only_paper_flag(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--only-paper", "paper_0012"])
        self.assertEqual(args.only_paper, "paper_0012")

    def test_only_paper_default_none(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertIsNone(args.only_paper)

    def test_pdf_dir_not_required_with_summarize_existing(self):
        """--pdf-dir should not be required when --summarize-existing is used."""
        args = self.parser.parse_args(["--summarize-existing", "--work-root", "/tmp/runs"])
        self.assertIsNone(args.pdf_dir)

    def test_pdf_dir_required_without_summarize_existing(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args([])


# ---------------------------------------------------------------------------
# ADR 021: Retry tracking in reports
# ---------------------------------------------------------------------------


class TestRetryTracking(unittest.TestCase):
    """ADR 021: retry history and tracking in markdown reports."""

    def test_retry_history_section_when_retries_exist(self):
        results = [
            _result(),
            _result(paper_id="beta_0002", retry_count=1,
                    previous_error="MinerU connection failed"),
        ]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("## Retry History", md)
        self.assertIn("beta_0002", md)
        self.assertIn("| 1 |", md)  # rerun count
        self.assertIn("MinerU connection failed", md)

    def test_no_retry_history_section_when_no_retries(self):
        results = [_result(), _result(paper_id="beta_0002")]
        md = _generate_markdown_report(results, 120.0)
        self.assertNotIn("## Retry History", md)

    def test_retry_column_in_per_paper_table(self):
        results = [
            _result(),
            _result(paper_id="beta_0002", retry_count=1,
                    previous_error="connection error"),
        ]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("Rtry", md)

    def test_no_retry_column_when_no_retries(self):
        results = [_result(), _result(paper_id="beta_0002")]
        md = _generate_markdown_report(results, 120.0)
        self.assertNotIn("Rtry", md)

    def test_final_status_shows_completed_after_retry(self):
        """A paper that was retried and succeeded shows completed status."""
        results = [
            _result(paper_id="beta_0002", retry_count=1,
                    previous_error="MinerU connection failed",
                    status="completed"),
        ]
        md = _generate_markdown_report(results, 120.0)
        self.assertIn("completed", md)
        self.assertIn("| 1 |", md)  # retry count

    def test_retry_count_tracked_in_json_summary(self):
        results = [_result(paper_id="beta_0002", retry_count=1,
                          previous_error="MinerU error")]
        summary = _generate_json_summary(results, 120.0)
        paper = summary["papers"][0]
        self.assertEqual(paper.get("retry_count", 0), 1)
        self.assertIsNotNone(paper.get("previous_error"))


# ---------------------------------------------------------------------------
# ADR 021: Summarize-existing mode
# ---------------------------------------------------------------------------


class TestSummarizeExisting(unittest.TestCase):
    """ADR 021: --summarize-existing functionality."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_run_report(self, paper_id: str, **overrides) -> Path:
        """Write a minimal run-report.json for a paper."""
        work_dir = self.tmpdir / paper_id
        work_dir.mkdir(parents=True, exist_ok=True)
        report_data = {
            "paper_id": paper_id,
            "status": "completed",
            "started_at": "2026-05-20T00:00:00+00:00",
            "finished_at": "2026-05-20T00:01:00+00:00",
            "steps": [
                {"name": "layout_ownership", "status": "success", "output_count": 21},
                {"name": "deepseek_structure", "status": "success", "output_count": 21},
                {"name": "identify_assets", "status": "success", "output_count": 3},
                {"name": "crop_assets", "status": "success", "output_count": 3, "warnings": []},
                {"name": "compute_phash", "status": "success", "output_count": 3},
                {"name": "duplicate_candidates", "status": "success", "output_count": 5},
                {"name": "visual_candidates", "status": "success", "output_count": 2},
            ],
            "counts": {},
            "warnings": [],
            "errors": [],
            "questions_passed": 20,
            "questions_warning": 1,
            "questions_failed": 0,
            "failed_question_ids": [],
            "quality_warning_counts": {"too_few_choices": 1},
        }
        report_data.update(overrides)
        report_path = work_dir / "run-report.json"
        report_path.write_text(json.dumps(report_data))
        return report_path

    def test_summarize_reads_existing_reports(self):
        """_summarize_from_existing reads run-report.json without calling ingest."""
        self._write_run_report("beta_0001")
        self._write_run_report("beta_0002")

        repo = mock.Mock()
        cursor = mock.Mock()
        cursor.fetchone.side_effect = [(3,), (0,), (0,), (3,), (0,), (0,)]
        repo.connection.cursor.return_value = cursor

        pdf_paths = [self.tmpdir / "beta_0001" / "placeholder.pdf",
                     self.tmpdir / "beta_0002" / "placeholder.pdf"]

        results = _summarize_from_existing(
            self.tmpdir, pdf_paths, "beta", repo,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["paper_id"], "beta_0001")
        self.assertEqual(results[0]["status"], "completed")
        self.assertEqual(results[0]["questions_passed"], 20)
        self.assertEqual(results[0]["raw_assets"], 3)
        self.assertEqual(results[0]["crop_success"], 3)
        self.assertEqual(results[0]["qa_links"], 3)

    def test_summarize_missing_report_returns_error(self):
        """A missing run-report.json produces an error entry."""
        pdf_paths = [self.tmpdir / "beta_0001" / "placeholder.pdf"]
        (self.tmpdir / "beta_0001").mkdir(parents=True, exist_ok=True)

        repo = mock.Mock()
        results = _summarize_from_existing(
            self.tmpdir, pdf_paths, "beta", repo,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "missing_report")
        self.assertIn("not found", results[0]["error"])

    def test_summarize_db_unavailable_raises(self):
        """If DB is unavailable, _summarize_from_existing raises RuntimeError."""
        self._write_run_report("beta_0001")

        # repo is None → DB unavailable
        pdf_paths = [self.tmpdir / "beta_0001" / "placeholder.pdf"]

        with self.assertRaises(RuntimeError) as ctx:
            _summarize_from_existing(self.tmpdir, pdf_paths, "beta", None)
        self.assertIn("Database unavailable", str(ctx.exception))

    def test_summarize_handles_db_query_failure(self):
        """When DB queries fail for a specific paper, raise RuntimeError."""
        self._write_run_report("beta_0001")

        repo = mock.Mock()
        cursor = mock.Mock()
        cursor.execute.side_effect = RuntimeError("DB connection dropped")
        repo.connection.cursor.return_value = cursor

        pdf_paths = [self.tmpdir / "beta_0001" / "placeholder.pdf"]

        with self.assertRaises(RuntimeError) as ctx:
            _summarize_from_existing(self.tmpdir, pdf_paths, "beta", repo)
        self.assertIn("Database unavailable", str(ctx.exception))

    def test_summarize_tracks_retry_from_previous_report(self):
        """If run-report.previous.json exists, retry_count is set."""
        self._write_run_report("beta_0001")
        prev_path = self.tmpdir / "beta_0001" / "run-report.previous.json"
        prev_path.write_text(json.dumps({
            "status": "failed",
            "errors": ["MinerU connection refused"],
        }))

        repo = mock.Mock()
        cursor = mock.Mock()
        cursor.fetchone.side_effect = [(3,), (0,), (0,)]
        repo.connection.cursor.return_value = cursor

        pdf_paths = [self.tmpdir / "beta_0001" / "placeholder.pdf"]

        results = _summarize_from_existing(
            self.tmpdir, pdf_paths, "beta", repo,
        )

        self.assertEqual(results[0]["retry_count"], 1)
        self.assertIn("MinerU", results[0]["previous_error"])

    def test_summarize_extracts_crop_failed_from_warnings(self):
        """crop_failed is computed from crop_assets warnings."""
        self._write_run_report("beta_0001", steps=[
            {"name": "layout_ownership", "status": "success", "output_count": 21},
            {"name": "deepseek_structure", "status": "success", "output_count": 21},
            {"name": "identify_assets", "status": "success", "output_count": 5},
            {"name": "crop_assets", "status": "warning", "output_count": 3,
             "warnings": ["img1: bad bbox", "img2: pdf error"]},
            {"name": "compute_phash", "status": "success", "output_count": 3},
            {"name": "duplicate_candidates", "status": "success", "output_count": 5},
            {"name": "visual_candidates", "status": "success", "output_count": 2},
        ])

        repo = mock.Mock()
        cursor = mock.Mock()
        cursor.fetchone.side_effect = [(3,), (0,), (0,)]
        repo.connection.cursor.return_value = cursor

        pdf_paths = [self.tmpdir / "beta_0001" / "placeholder.pdf"]

        results = _summarize_from_existing(
            self.tmpdir, pdf_paths, "beta", repo,
        )

        self.assertEqual(results[0]["crop_success"], 3)
        self.assertEqual(results[0]["crop_failed"], 2)

    def test_summarize_failed_paper_has_error_field(self):
        """Failed papers get error field from report errors."""
        self._write_run_report("beta_0001", status="failed",
                              errors=["mineru_parse: MinerU crashed"])

        repo = mock.Mock()
        cursor = mock.Mock()
        cursor.fetchone.side_effect = [(0,), (0,), (0,)]
        repo.connection.cursor.return_value = cursor

        pdf_paths = [self.tmpdir / "beta_0001" / "placeholder.pdf"]

        results = _summarize_from_existing(
            self.tmpdir, pdf_paths, "beta", repo,
        )

        self.assertEqual(results[0]["status"], "failed")
        self.assertIn("MinerU crashed", results[0]["error"])


if __name__ == "__main__":
    unittest.main()
