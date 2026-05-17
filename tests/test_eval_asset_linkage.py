"""Tests for ADR 011: Non-dry-run asset linkage evaluation tool."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.eval_asset_linkage import (
    _build_parser,
    _build_result_row,
    _check_schema,
    _classify_error,
    _classify_warning,
    _count_mineru_element_types,
    _generate_report,
    _query_asset_metrics,
    _visual_count,
)


class ArgumentParsingTest(unittest.TestCase):
    def test_required_pdf_dir(self):
        parser = _build_parser()
        args = parser.parse_args(["--pdf-dir", "data/beta/pdf"])
        self.assertEqual(args.pdf_dir, Path("data/beta/pdf"))

    def test_default_limit_5(self):
        parser = _build_parser()
        args = parser.parse_args(["--pdf-dir", "data/beta/pdf"])
        self.assertEqual(args.limit, 5)

    def test_custom_limit(self):
        parser = _build_parser()
        args = parser.parse_args(["--pdf-dir", "data/beta/pdf", "--limit", "3"])
        self.assertEqual(args.limit, 3)

    def test_paper_prefix_default(self):
        parser = _build_parser()
        args = parser.parse_args(["--pdf-dir", "data/beta/pdf"])
        self.assertEqual(args.paper_prefix, "asset_eval")

    def test_custom_paper_prefix(self):
        parser = _build_parser()
        args = parser.parse_args(
            ["--pdf-dir", "data/beta/pdf", "--paper-prefix", "my_test"]
        )
        self.assertEqual(args.paper_prefix, "my_test")

    def test_db_url_optional(self):
        parser = _build_parser()
        args = parser.parse_args(["--pdf-dir", "data/beta/pdf"])
        self.assertIsNone(args.db_url)

    def test_custom_db_url(self):
        parser = _build_parser()
        args = parser.parse_args(
            ["--pdf-dir", "data/beta/pdf", "--db-url",
             "postgresql://localhost:5432/testdb"]
        )
        self.assertEqual(args.db_url, "postgresql://localhost:5432/testdb")

    def test_resume_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["--pdf-dir", "data/beta/pdf", "--resume"])
        self.assertTrue(args.resume)

    def test_fail_fast_flag(self):
        parser = _build_parser()
        args = parser.parse_args(["--pdf-dir", "data/beta/pdf", "--fail-fast"])
        self.assertTrue(args.fail_fast)


class SchemaCheckTest(unittest.TestCase):
    def test_returns_missing_tables(self):
        """_check_schema returns list of required tables that are missing."""
        fake_conn = mock.Mock()
        cursor = mock.Mock()
        fake_conn.cursor.return_value = cursor
        # Simulate only 3 tables exist
        cursor.fetchall.return_value = [
            ("papers",), ("parse_runs",), ("question_blocks",),
        ]
        missing = _check_schema(fake_conn)
        self.assertIn("raw_assets", missing)
        self.assertIn("question_asset_links", missing)
        self.assertNotIn("papers", missing)

    def test_returns_empty_when_all_present(self):
        """_check_schema returns [] when all required tables exist."""
        fake_conn = mock.Mock()
        cursor = mock.Mock()
        fake_conn.cursor.return_value = cursor
        cursor.fetchall.return_value = [
            (t,) for t in [
                "papers", "parse_runs", "question_blocks", "questions",
                "choices", "question_assets", "raw_assets", "question_asset_links",
            ]
        ]
        missing = _check_schema(fake_conn)
        self.assertEqual(missing, [])


class VisualCountTest(unittest.TestCase):
    def test_sums_image_table_chart(self):
        self.assertEqual(
            _visual_count({"image": 5, "table": 2, "chart": 1, "text": 100}),
            8,
        )

    def test_zero_when_none(self):
        self.assertEqual(_visual_count({"text": 50, "equation": 10}), 0)

    def test_empty_dict(self):
        self.assertEqual(_visual_count({}), 0)


class ElementTypeCountTest(unittest.TestCase):
    def test_reads_content_list_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir) / "paper_test" / "auto"
            work_dir.mkdir(parents=True)
            (work_dir / "paper_test_content_list.json").write_text(json.dumps([
                {"type": "text", "text": "hello"},
                {"type": "image", "text": ""},
                {"type": "image", "text": ""},
                {"type": "table", "text": ""},
            ]))

            counts = _count_mineru_element_types(work_dir, "paper_test")
            self.assertEqual(counts, {"text": 1, "image": 2, "table": 1})

    def test_falls_back_to_middle_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir) / "paper_fb" / "txt"
            work_dir.mkdir(parents=True)
            # Create middle.json instead of content_list
            (work_dir / "paper_fb_middle.json").write_text(json.dumps(
                [{"type": "equation", "text": "x=1"}]
            ))

            counts = _count_mineru_element_types(work_dir, "paper_fb")
            self.assertEqual(counts, {"equation": 1})

    def test_no_json_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = Path(tmpdir) / "paper_empty" / "auto"
            work_dir.mkdir(parents=True)
            # No JSON files at all
            counts = _count_mineru_element_types(work_dir, "paper_empty")
            self.assertEqual(counts, {})


class DBQueryTest(unittest.TestCase):
    def test_queries_asset_metrics(self):
        """_query_asset_metrics returns a dict with expected keys."""
        fake_conn = mock.Mock()
        cursor = mock.Mock()
        fake_conn.cursor.return_value = cursor

        # Simulate fetchone returns for each query
        cursor.fetchone.side_effect = [
            (5,),   # raw_assets count
            (3,),   # links count
            (2,),   # unassigned count
            (1,),   # low confidence count
        ]

        metrics = _query_asset_metrics(fake_conn, "paper_001")
        self.assertEqual(metrics["raw_assets"], 5)
        self.assertEqual(metrics["links"], 3)
        self.assertEqual(metrics["unassigned"], 2)
        self.assertEqual(metrics["low_confidence"], 1)


class ResultRowTest(unittest.TestCase):
    def setUp(self):
        from question_bank.services.paper_orchestrator import (
            IngestionReport,
            StepResult,
        )

        self.success_report = IngestionReport(
            paper_id="asset_eval_001",
            status="completed",
            started_at="", finished_at="",
            steps=[
                StepResult(name="mineru_parse", status="success",
                           started_at="", finished_at="",
                           input_count=1, output_count=1),
                StepResult(name="layout_ownership", status="success",
                           started_at="", finished_at="",
                           input_count=100, output_count=20),
                StepResult(name="deepseek_structure", status="success",
                           started_at="", finished_at="",
                           input_count=20, output_count=20),
                StepResult(name="identify_assets", status="success",
                           started_at="", finished_at="",
                           input_count=20, output_count=8),
                StepResult(name="crop_assets", status="success",
                           started_at="", finished_at="",
                           input_count=8, output_count=8),
                StepResult(name="store_assets", status="success",
                           started_at="", finished_at="",
                           input_count=8, output_count=8),
                StepResult(name="compute_phash", status="success",
                           started_at="", finished_at="",
                           input_count=8, output_count=8),
            ],
            counts={"steps_total": 10, "steps_succeeded": 7,
                    "steps_warning": 0, "steps_failed": 0, "steps_skipped": 3},
            warnings=[],
            errors=[],
        )

    def test_success_row_with_db_metrics(self):
        entry = {
            "paper_id": "asset_eval_001",
            "pages": 8,
            "work_dir": "/tmp/runs/asset_eval_001",
            "mineru_types": {"text": 100, "image": 5, "table": 2, "chart": 1},
            "report": self.success_report,
            "error": None,
        }
        db_metrics = {
            "raw_assets": 8, "links": 6,
            "unassigned": 2, "low_confidence": 1,
        }
        row = _build_result_row(entry, db_metrics)

        self.assertEqual(row["paper_id"], "asset_eval_001")
        self.assertEqual(row["pages"], 8)
        self.assertEqual(row["layout_q"], 20)
        self.assertEqual(row["mineru_visual"], 8)  # 5+2+1
        self.assertEqual(row["raw_assets"], 8)
        self.assertEqual(row["links"], 6)
        self.assertEqual(row["crop_success"], 8)
        self.assertEqual(row["crop_failed"], 0)
        self.assertEqual(row["phash_success"], 8)
        self.assertEqual(row["unassigned"], 2)
        self.assertEqual(row["low_confidence"], 1)
        self.assertEqual(row["status"], "completed")

    def test_row_with_crop_warnings(self):
        from question_bank.services.paper_orchestrator import (
            IngestionReport,
            StepResult,
        )

        report = IngestionReport(
            paper_id="asset_eval_002",
            status="partial",
            started_at="", finished_at="",
            steps=[
                StepResult(name="mineru_parse", status="success",
                           started_at="", finished_at="",
                           input_count=1, output_count=1),
                StepResult(name="layout_ownership", status="success",
                           started_at="", finished_at="",
                           input_count=50, output_count=15),
                StepResult(name="identify_assets", status="success",
                           started_at="", finished_at="",
                           input_count=15, output_count=6),
                StepResult(name="crop_assets", status="warning",
                           started_at="", finished_at="",
                           input_count=6, output_count=4,
                           warnings=["ra_001: bbox out of page bounds",
                                     "ra_002: zero-area crop"]),
                StepResult(name="compute_phash", status="success",
                           started_at="", finished_at="",
                           input_count=6, output_count=4),
            ],
            counts={"steps_total": 10, "steps_succeeded": 5,
                    "steps_warning": 1, "steps_failed": 0, "steps_skipped": 4},
            warnings=["ra_001: bbox out of page bounds",
                      "ra_002: zero-area crop"],
            errors=[],
        )
        entry = {
            "paper_id": "asset_eval_002",
            "pages": 4,
            "work_dir": "/tmp/runs/asset_eval_002",
            "mineru_types": {"text": 50, "image": 6},
            "report": report,
            "error": None,
        }
        db_metrics = {"raw_assets": 6, "links": 4,
                      "unassigned": 2, "low_confidence": 0}

        row = _build_result_row(entry, db_metrics)
        self.assertEqual(row["crop_success"], 4)
        self.assertEqual(row["crop_failed"], 2)
        self.assertEqual(row["phash_success"], 4)
        self.assertEqual(row["status"], "partial")

    def test_crash_row_without_db(self):
        entry = {
            "paper_id": "asset_eval_003",
            "pages": "?",
            "work_dir": "/tmp/runs/asset_eval_003",
            "mineru_types": {},
            "report": None,
            "error": "DB connection failed: connection refused",
        }
        row = _build_result_row(entry, None)
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["errors"], 1)
        self.assertIn("DB connection", row["error_detail"])


class ReportGenerationTest(unittest.TestCase):
    def setUp(self):
        from question_bank.services.paper_orchestrator import (
            IngestionReport,
            StepResult,
        )

        self.good_report = IngestionReport(
            paper_id="asset_eval_001",
            status="completed",
            started_at="", finished_at="",
            steps=[
                StepResult(name="mineru_parse", status="success",
                           started_at="", finished_at="",
                           input_count=1, output_count=1),
                StepResult(name="layout_ownership", status="success",
                           started_at="", finished_at="",
                           input_count=80, output_count=15),
                StepResult(name="deepseek_structure", status="success",
                           started_at="", finished_at="",
                           input_count=15, output_count=15),
                StepResult(name="identify_assets", status="success",
                           started_at="", finished_at="",
                           input_count=15, output_count=6),
                StepResult(name="crop_assets", status="success",
                           started_at="", finished_at="",
                           input_count=6, output_count=6),
                StepResult(name="compute_phash", status="success",
                           started_at="", finished_at="",
                           input_count=6, output_count=6),
            ],
            counts={"steps_total": 10, "steps_succeeded": 6,
                    "steps_warning": 0, "steps_failed": 0, "steps_skipped": 4},
            warnings=[],
            errors=[],
        )

    def test_report_contains_asset_sections(self):
        results = [
            {"paper_id": "asset_eval_001", "pages": 6,
             "work_dir": "/tmp/runs/p1",
             "mineru_types": {"text": 80, "image": 4, "table": 2},
             "report": self.good_report, "error": None},
        ]
        db_metrics_list = [
            {"raw_assets": 6, "links": 5, "unassigned": 1, "low_confidence": 0},
        ]
        args = mock.Mock(paper_prefix="asset_eval")

        content = _generate_report(results, db_metrics_list, 30.0, args)

        self.assertIn("# Asset Linkage Evaluation", content)
        self.assertIn("## Summary", content)
        self.assertIn("## Asset Metrics (Aggregate)", content)
        self.assertIn("## Per-Paper Results", content)
        self.assertIn("## Per-Paper Detail", content)
        self.assertIn("## Conclusion", content)
        self.assertIn("asset_eval_001", content)
        self.assertIn("MinerU visual elements", content)
        self.assertIn("raw_assets rows", content)

    def test_report_passing_verdict(self):
        results = [
            {"paper_id": "asset_eval_001", "pages": 6,
             "work_dir": "/tmp/runs/p1",
             "mineru_types": {"text": 80, "image": 4},
             "report": self.good_report, "error": None},
        ]
        db_metrics_list = [
            {"raw_assets": 4, "links": 4, "unassigned": 0, "low_confidence": 0},
        ]
        args = mock.Mock(paper_prefix="asset_eval")
        content = _generate_report(results, db_metrics_list, 30.0, args)
        self.assertIn("**PASS**", content)

    def test_report_blocked_when_no_links_despite_visuals(self):
        results = [
            {"paper_id": "asset_eval_001", "pages": 6,
             "work_dir": "/tmp/runs/p1",
             "mineru_types": {"text": 80, "image": 4},
             "report": self.good_report, "error": None},
        ]
        db_metrics_list = [
            {"raw_assets": 0, "links": 0, "unassigned": 4, "low_confidence": 0},
        ]
        args = mock.Mock(paper_prefix="asset_eval")
        content = _generate_report(results, db_metrics_list, 30.0, args)
        self.assertIn("**BLOCKED**", content)

    def test_report_includes_failure_reasons(self):
        from question_bank.services.paper_orchestrator import (
            IngestionReport,
            StepResult,
        )

        bad_report = IngestionReport(
            paper_id="asset_eval_bad",
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
        results = [
            {"paper_id": "asset_eval_bad", "pages": 3,
             "work_dir": "/tmp/runs/p1",
             "mineru_types": {}, "report": bad_report, "error": None},
        ]
        args = mock.Mock(paper_prefix="asset_eval")
        content = _generate_report(results, [None], 10.0, args)
        self.assertIn("## Top Failure Reasons", content)
        self.assertIn("MinerU", content)

    def test_report_includes_warning_patterns(self):
        from question_bank.services.paper_orchestrator import (
            IngestionReport,
            StepResult,
        )

        warn_report = IngestionReport(
            paper_id="asset_eval_warn",
            status="partial",
            started_at="", finished_at="",
            steps=[
                StepResult(name="mineru_parse", status="success",
                           started_at="", finished_at="",
                           input_count=1, output_count=1),
                StepResult(name="crop_assets", status="warning",
                           started_at="", finished_at="",
                           input_count=5, output_count=3,
                           warnings=["ra_x: crop region empty",
                                     "ra_y: PDF page not found"]),
            ],
            counts={"steps_total": 10, "steps_succeeded": 5,
                    "steps_warning": 1, "steps_failed": 0, "steps_skipped": 4},
            warnings=["ra_x: crop region empty", "ra_y: PDF page not found"],
            errors=[],
        )
        results = [
            {"paper_id": "asset_eval_warn", "pages": 4,
             "work_dir": "/tmp/runs/p1",
             "mineru_types": {"text": 50, "image": 5},
             "report": warn_report, "error": None},
        ]
        args = mock.Mock(paper_prefix="asset_eval")
        content = _generate_report(results, [None], 15.0, args)
        self.assertIn("## Top Warning Patterns", content)
        self.assertIn("Crop", content)


class ErrorClassificationTest(unittest.TestCase):
    def test_db_connection_error(self):
        self.assertIn("Database",
                       _classify_error("psycopg connection refused"))

    def test_schema_missing(self):
        self.assertIn("Schema",
                       _classify_error("schema validation failed: missing raw_assets"))

    def test_mineru_error(self):
        self.assertIn("MinerU",
                       _classify_error("MinerU exited with code 1"))


class WarningClassificationTest(unittest.TestCase):
    def test_crop_warning(self):
        self.assertIn("Crop",
                       _classify_warning("crop failed for asset ra_001"))

    def test_phash_warning(self):
        self.assertIn("pHash",
                       _classify_warning("phash computation error: bad image"))

    def test_save_warning(self):
        self.assertIn("Save",
                       _classify_warning("save_duplicate_candidate_group failed"))


if __name__ == "__main__":
    unittest.main()
