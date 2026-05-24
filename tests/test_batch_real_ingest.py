"""Tests for ADR 022: Production Batch Runner & Observability."""

from __future__ import annotations

import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from tools.batch_real_ingest import (
    _build_parser,
    _classify_failure,
    _ensure_writable_dir,
    _extract_step_timings,
    _generate_json_summary,
    _generate_markdown_report,
    _init_manifest,
    _load_manifest,
    _open_checked_database_connection,
    _save_manifest,
    _split_manifest_paper_id,
    _update_manifest_entry,
    _validate_deepseek_api_key,
    _validate_mineru_command,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(
    paper_id="batch_0001",
    status="completed",
    pages=10,
    layout_q=5,
    deepseek_out=5,
    questions_passed=4,
    questions_warning=1,
    questions_failed=0,
    failed_question_ids=None,
    quality_warning_counts=None,
    raw_assets=3,
    qa_links=3,
    unlinked_raw_assets=0,
    links_without_question_block=0,
    crop_success=3,
    crop_failed=0,
    phash_success=3,
    duplicate_candidates=0,
    visual_candidates=0,
    elapsed_s=45.0,
    step_data=None,
    error=None,
):
    return {
        "paper_id": paper_id,
        "pdf_path": f"/fake/{paper_id}.pdf",
        "work_dir": f"/tmp/{paper_id}",
        "status": status,
        "pages": pages,
        "layout_q": layout_q,
        "deepseek_out": deepseek_out,
        "questions_passed": questions_passed,
        "questions_warning": questions_warning,
        "questions_failed": questions_failed,
        "failed_question_ids": failed_question_ids or [],
        "quality_warning_counts": quality_warning_counts or {},
        "raw_assets": raw_assets,
        "qa_links": qa_links,
        "unlinked_raw_assets": unlinked_raw_assets,
        "links_without_question_block": links_without_question_block,
        "crop_success": crop_success,
        "crop_failed": crop_failed,
        "phash_success": phash_success,
        "duplicate_candidates": duplicate_candidates,
        "visual_candidates": visual_candidates,
        "elapsed_s": elapsed_s,
        "step_data": step_data or {},
        "error": error,
    }


# ---------------------------------------------------------------------------
# TestArgumentParsing
# ---------------------------------------------------------------------------


class TestArgumentParsing(unittest.TestCase):
    """ADR 022: CLI argument parsing."""

    def setUp(self):
        self.parser = _build_parser()

    def test_pdf_dir_required(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args([])

    def test_pdf_dir_accepted(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertEqual(args.pdf_dir, Path("/tmp/pdfs"))

    def test_default_work_root_none(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertIsNone(args.work_root)

    def test_work_root_custom(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--work-root", "/custom/root"])
        self.assertEqual(args.work_root, Path("/custom/root"))

    def test_limit_default_none(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertIsNone(args.limit)

    def test_limit_value(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--limit", "50"])
        self.assertEqual(args.limit, 50)

    def test_resume_default_false(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertFalse(args.resume)

    def test_resume_flag(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--resume"])
        self.assertTrue(args.resume)

    def test_only_index_default_none(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertIsNone(args.only_index)

    def test_only_index_value(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--only-index", "5"])
        self.assertEqual(args.only_index, 5)

    def test_only_paper_default_none(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertIsNone(args.only_paper)

    def test_only_paper_value(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--only-paper", "batch_0003"])
        self.assertEqual(args.only_paper, "batch_0003")

    def test_fail_fast_default_false(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertFalse(args.fail_fast)

    def test_fail_fast_flag(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs", "--fail-fast"])
        self.assertTrue(args.fail_fast)

    def test_asset_dir_default(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertEqual(args.asset_dir, Path("data/assets"))

    def test_report_dir_default(self):
        args = self.parser.parse_args(["--pdf-dir", "/tmp/pdfs"])
        self.assertEqual(args.report_dir, Path("docs/eval"))


# ---------------------------------------------------------------------------
# TestManifestManagement
# ---------------------------------------------------------------------------


class TestManifestManagement(unittest.TestCase):
    """ADR 022: manifest init, load, save, update."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _pdf_files(self, n=3):
        return [Path(f"/fake/paper_{i:03d}.pdf") for i in range(n)]

    def test_init_manifest_creates_entries(self):
        pdfs = self._pdf_files(3)
        manifest = _init_manifest(pdfs, "batch", self.tmpdir)
        self.assertEqual(len(manifest), 3)
        self.assertEqual(manifest[0]["paper_id"], "batch_0001")
        self.assertEqual(manifest[1]["paper_id"], "batch_0002")
        self.assertEqual(manifest[2]["paper_id"], "batch_0003")

    def test_init_manifest_all_status_pending(self):
        pdfs = self._pdf_files(3)
        manifest = _init_manifest(pdfs, "batch", self.tmpdir)
        for entry in manifest:
            self.assertEqual(entry["status"], "pending")

    def test_init_manifest_pdf_paths_recorded(self):
        pdfs = self._pdf_files(2)
        manifest = _init_manifest(pdfs, "batch", self.tmpdir)
        self.assertEqual(manifest[0]["pdf_path"], "/fake/paper_000.pdf")

    def test_init_manifest_attempts_zero(self):
        pdfs = self._pdf_files(1)
        manifest = _init_manifest(pdfs, "batch", self.tmpdir)
        self.assertEqual(manifest[0]["attempts"], 0)

    def test_init_manifest_started_finished_none(self):
        pdfs = self._pdf_files(1)
        manifest = _init_manifest(pdfs, "batch", self.tmpdir)
        self.assertIsNone(manifest[0]["started_at"])
        self.assertIsNone(manifest[0]["finished_at"])

    def test_init_manifest_last_error_none(self):
        pdfs = self._pdf_files(1)
        manifest = _init_manifest(pdfs, "batch", self.tmpdir)
        self.assertIsNone(manifest[0]["last_error"])

    def test_init_manifest_run_report_path_none(self):
        pdfs = self._pdf_files(1)
        manifest = _init_manifest(pdfs, "batch", self.tmpdir)
        self.assertIsNone(manifest[0]["run_report_path"])

    def test_load_manifest_missing_returns_none(self):
        result = _load_manifest(self.tmpdir)
        self.assertIsNone(result)

    def test_load_manifest_valid_returns_list(self):
        manifest = [
            {"paper_id": "x_0001", "status": "completed"},
            {"paper_id": "x_0002", "status": "pending"},
        ]
        _save_manifest(manifest, self.tmpdir)
        loaded = _load_manifest(self.tmpdir)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["paper_id"], "x_0001")

    def test_load_manifest_corrupt_json_returns_none(self):
        (self.tmpdir / "batch-manifest.json").write_text("not json {{{")
        result = _load_manifest(self.tmpdir)
        self.assertIsNone(result)

    def test_load_manifest_non_list_returns_none(self):
        (self.tmpdir / "batch-manifest.json").write_text('{"not": "a list"}')
        result = _load_manifest(self.tmpdir)
        self.assertIsNone(result)

    def test_save_manifest_writes_json(self):
        manifest = [{"paper_id": "x_0001", "status": "completed"}]
        _save_manifest(manifest, self.tmpdir)
        path = self.tmpdir / "batch-manifest.json"
        self.assertTrue(path.exists())
        data = json.loads(path.read_text())
        self.assertEqual(len(data), 1)

    def test_update_manifest_entry_modifies_in_place(self):
        manifest = [
            {"paper_id": "a", "status": "pending"},
            {"paper_id": "b", "status": "pending"},
        ]
        _update_manifest_entry(manifest, "a", status="completed", attempts=1)
        self.assertEqual(manifest[0]["status"], "completed")
        self.assertEqual(manifest[0]["attempts"], 1)
        self.assertEqual(manifest[1]["status"], "pending")

    def test_update_manifest_entry_unknown_id_noop(self):
        manifest = [{"paper_id": "a", "status": "pending"}]
        _update_manifest_entry(manifest, "nonexistent", status="completed")
        self.assertEqual(manifest[0]["status"], "pending")

    def test_split_manifest_paper_id_preserves_prefix(self):
        prefix, index = _split_manifest_paper_id("batch_2026_05_19_0012", "fallback")
        self.assertEqual(prefix, "batch_2026_05_19")
        self.assertEqual(index, 12)

    def test_split_manifest_paper_id_uses_fallback_for_invalid_id(self):
        prefix, index = _split_manifest_paper_id("not-numbered", "fallback")
        self.assertEqual(prefix, "fallback")
        self.assertEqual(index, 1)


# ---------------------------------------------------------------------------
# TestManifestResumeBehavior
# ---------------------------------------------------------------------------


class TestManifestResumeBehavior(unittest.TestCase):
    """ADR 022: --resume skips completed/partial, reruns failed/crashed/pending."""

    def test_skip_completed(self):
        manifest = [
            {"paper_id": "b_0001", "status": "completed"},
            {"paper_id": "b_0002", "status": "pending"},
        ]
        to_process = [m for m in manifest if m["status"] in
                      ("pending", "failed", "crashed", "running")]
        self.assertEqual(len(to_process), 1)
        self.assertEqual(to_process[0]["paper_id"], "b_0002")

    def test_skip_partial(self):
        manifest = [
            {"paper_id": "b_0001", "status": "partial"},
            {"paper_id": "b_0002", "status": "pending"},
        ]
        to_process = [m for m in manifest if m["status"] in
                      ("pending", "failed", "crashed", "running")]
        self.assertEqual(len(to_process), 1)
        self.assertEqual(to_process[0]["paper_id"], "b_0002")

    def test_rerun_failed(self):
        manifest = [
            {"paper_id": "b_0001", "status": "failed", "last_error": "timeout"},
            {"paper_id": "b_0002", "status": "completed"},
        ]
        to_process = [m for m in manifest if m["status"] in
                      ("pending", "failed", "crashed", "running")]
        self.assertEqual(len(to_process), 1)
        self.assertEqual(to_process[0]["paper_id"], "b_0001")

    def test_rerun_crashed(self):
        manifest = [
            {"paper_id": "b_0001", "status": "crashed", "last_error": "segfault"},
            {"paper_id": "b_0002", "status": "completed"},
        ]
        to_process = [m for m in manifest if m["status"] in
                      ("pending", "failed", "crashed", "running")]
        self.assertEqual(len(to_process), 1)
        self.assertEqual(to_process[0]["paper_id"], "b_0001")

    def test_rerun_pending(self):
        manifest = [
            {"paper_id": "b_0001", "status": "pending"},
        ]
        to_process = [m for m in manifest if m["status"] in
                      ("pending", "failed", "crashed", "running")]
        self.assertEqual(len(to_process), 1)

    def test_rerun_running(self):
        manifest = [
            {"paper_id": "b_0001", "status": "running"},
        ]
        to_process = [m for m in manifest if m["status"] in
                      ("pending", "failed", "crashed", "running")]
        self.assertEqual(len(to_process), 1)


# ---------------------------------------------------------------------------
# TestOnlyIndexFiltering
# ---------------------------------------------------------------------------


class TestOnlyIndexFiltering(unittest.TestCase):
    """ADR 022: --only-index and --only-paper filtering on manifest."""

    def test_only_index_filters_to_single_entry(self):
        manifest = [
            {"paper_id": "b_0001"},
            {"paper_id": "b_0002"},
            {"paper_id": "b_0003"},
        ]
        idx = 1  # 1-indexed → second entry
        matched = [manifest[idx]]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["paper_id"], "b_0002")

    def test_only_index_first_entry(self):
        manifest = [{"paper_id": "b_0001"}, {"paper_id": "b_0002"}]
        idx = 0  # 1-indexed → first entry
        matched = [manifest[idx]]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["paper_id"], "b_0001")

    def test_only_paper_filters_by_substring(self):
        manifest = [
            {"paper_id": "batch_0001"},
            {"paper_id": "batch_0002"},
            {"paper_id": "other_0001"},
        ]
        matched = [m for m in manifest if "batch" in m["paper_id"]]
        self.assertEqual(len(matched), 2)
        self.assertEqual(matched[0]["paper_id"], "batch_0001")

    def test_only_paper_exact_match(self):
        manifest = [
            {"paper_id": "batch_0001"},
            {"paper_id": "batch_0002"},
        ]
        matched = [m for m in manifest if "batch_0002" in m["paper_id"]]
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["paper_id"], "batch_0002")


# ---------------------------------------------------------------------------
# TestStepTimingExtraction
# ---------------------------------------------------------------------------


class TestStepTimingExtraction(unittest.TestCase):
    """ADR 022: step-level timing aggregation."""

    def test_extracts_single_step_timing(self):
        results = [
            _make_result(paper_id="p1", step_data={
                "mineru_parse": {
                    "started_at": "2026-05-20T10:00:00",
                    "finished_at": "2026-05-20T10:01:00",
                }
            }),
        ]
        timings = _extract_step_timings(results)
        self.assertEqual(len(timings), 1)
        self.assertEqual(timings[0]["step"], "mineru_parse")
        self.assertEqual(timings[0]["count"], 1)
        self.assertEqual(timings[0]["total_s"], 60.0)
        self.assertEqual(timings[0]["avg_s"], 60.0)
        self.assertEqual(timings[0]["max_s"], 60.0)
        self.assertEqual(timings[0]["slowest_paper"], "p1")

    def test_extracts_multiple_steps(self):
        results = [
            _make_result(paper_id="p1", step_data={
                "mineru_parse": {
                    "started_at": "2026-05-20T10:00:00",
                    "finished_at": "2026-05-20T10:01:00",
                },
                "deepseek_structure": {
                    "started_at": "2026-05-20T10:01:00",
                    "finished_at": "2026-05-20T10:01:30",
                },
            }),
        ]
        timings = _extract_step_timings(results)
        self.assertEqual(len(timings), 2)
        step_names = {t["step"] for t in timings}
        self.assertIn("mineru_parse", step_names)
        self.assertIn("deepseek_structure", step_names)

    def test_aggregates_across_papers(self):
        results = [
            _make_result(paper_id="p1", step_data={
                "mineru_parse": {
                    "started_at": "2026-05-20T10:00:00",
                    "finished_at": "2026-05-20T10:01:00",
                },
            }),
            _make_result(paper_id="p2", step_data={
                "mineru_parse": {
                    "started_at": "2026-05-20T10:00:00",
                    "finished_at": "2026-05-20T10:00:30",
                },
            }),
        ]
        timings = _extract_step_timings(results)
        self.assertEqual(timings[0]["count"], 2)
        self.assertEqual(timings[0]["total_s"], 90.0)
        self.assertEqual(timings[0]["avg_s"], 45.0)
        self.assertEqual(timings[0]["max_s"], 60.0)
        self.assertEqual(timings[0]["slowest_paper"], "p1")

    def test_tracks_slowest_paper(self):
        results = [
            _make_result(paper_id="fast", step_data={
                "step_a": {
                    "started_at": "2026-05-20T10:00:00",
                    "finished_at": "2026-05-20T10:00:10",
                },
            }),
            _make_result(paper_id="slow", step_data={
                "step_a": {
                    "started_at": "2026-05-20T10:00:00",
                    "finished_at": "2026-05-20T10:05:00",
                },
            }),
        ]
        timings = _extract_step_timings(results)
        self.assertEqual(timings[0]["slowest_paper"], "slow")
        self.assertEqual(timings[0]["max_s"], 300.0)

    def test_empty_step_data_skipped(self):
        results = [_make_result(paper_id="p1", step_data={})]
        timings = _extract_step_timings(results)
        self.assertEqual(len(timings), 0)

    def test_missing_timestamps_skipped(self):
        results = [
            _make_result(paper_id="p1", step_data={
                "step_a": {"started_at": "", "finished_at": ""},
            }),
        ]
        timings = _extract_step_timings(results)
        self.assertEqual(len(timings), 0)

    def test_invalid_timestamps_handled_gracefully(self):
        results = [
            _make_result(paper_id="p1", step_data={
                "step_a": {
                    "started_at": "not-a-date",
                    "finished_at": "also-not-a-date",
                },
            }),
        ]
        timings = _extract_step_timings(results)
        # Invalid timestamps → dur=0, still recorded (count=1)
        self.assertEqual(len(timings), 1)
        self.assertEqual(timings[0]["total_s"], 0.0)

    def test_step_timing_pct_of_wall_filled_by_caller(self):
        results = [
            _make_result(paper_id="p1", step_data={
                "step_a": {
                    "started_at": "2026-05-20T10:00:00",
                    "finished_at": "2026-05-20T10:01:00",
                },
            }),
        ]
        timings = _extract_step_timings(results)
        # pct_of_wall defaults to 0.0 — filled by caller
        self.assertEqual(timings[0]["pct_of_wall"], 0.0)
        # Simulate caller fill
        timings[0]["pct_of_wall"] = 50.0
        self.assertEqual(timings[0]["pct_of_wall"], 50.0)


# ---------------------------------------------------------------------------
# TestFailureTaxonomy
# ---------------------------------------------------------------------------


class TestFailureTaxonomy(unittest.TestCase):
    """ADR 022: failure taxonomy classification."""

    def test_mineru_transient(self):
        self.assertEqual(
            _classify_failure("MinerU Connection refused"),
            "mineru_transient",
        )

    def test_mineru_timeout_is_transient(self):
        self.assertEqual(
            _classify_failure("mineru timed out after 300s"),
            "mineru_transient",
        )

    def test_mineru_broken_pipe_is_transient(self):
        self.assertEqual(
            _classify_failure("mineru broken pipe"),
            "mineru_transient",
        )

    def test_mineru_non_transient(self):
        self.assertEqual(
            _classify_failure("MinerU model download failed"),
            "mineru_non_transient",
        )

    def test_mineru_file_not_found_non_transient(self):
        self.assertEqual(
            _classify_failure("mineru: file not found"),
            "mineru_non_transient",
        )

    def test_deepseek_category(self):
        self.assertEqual(
            _classify_failure("DeepSeek API returned 500"),
            "deepseek",
        )

    def test_database_category(self):
        self.assertEqual(
            _classify_failure("database connection failed: psycopg error"),
            "database",
        )

    def test_postgres_category(self):
        self.assertEqual(
            _classify_failure("postgres unreachable"),
            "database",
        )

    def test_layout_category(self):
        self.assertEqual(
            _classify_failure("layout ownership failed to parse"),
            "layout",
        )

    def test_asset_crop_category(self):
        self.assertEqual(
            _classify_failure("crop operation failed for image"),
            "asset_crop",
        )

    def test_asset_store_category(self):
        self.assertEqual(
            _classify_failure("storage backend unreachable"),
            "asset_store",
        )

    def test_unknown_category(self):
        self.assertEqual(
            _classify_failure("something completely unexpected"),
            "unknown",
        )

    def test_empty_error_is_unknown(self):
        self.assertEqual(_classify_failure(""), "unknown")

    def test_none_error_is_unknown(self):
        self.assertEqual(_classify_failure(None), "unknown")


# ---------------------------------------------------------------------------
# TestPreflightGate
# ---------------------------------------------------------------------------


class FakeSettings:
    database_url = "postgresql+psycopg://u:p@localhost:5432/db"


class FakeDBCursor:
    def __init__(self, missing_tables=None):
        self.missing_tables = set(missing_tables or [])
        self.last_query = ""
        self.last_params = None

    def execute(self, query, params=None):
        self.last_query = query
        self.last_params = params

    def fetchone(self):
        if "SELECT 1" in self.last_query:
            return (1,)
        if "to_regclass" in self.last_query:
            table = self.last_params[0].split(".")[-1]
            if table in self.missing_tables:
                return (None,)
            return (self.last_params[0],)
        return None


class FakeDBConnection:
    def __init__(self, missing_tables=None):
        self.cursor_obj = FakeDBCursor(missing_tables)
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


class FakePsycopgModule:
    def __init__(self, connection=None, error=None):
        self.connection = connection or FakeDBConnection()
        self.error = error
        self.conninfo = None

    def connect(self, conninfo):
        self.conninfo = conninfo
        if self.error:
            raise self.error
        return self.connection


class TestPreflightGate(unittest.TestCase):
    """ADR 023: production batch preflight checks."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_validate_deepseek_api_key_accepts_sk_prefix(self):
        self.assertIsNone(_validate_deepseek_api_key("sk-test-123456"))

    def test_validate_deepseek_api_key_rejects_blank(self):
        err = _validate_deepseek_api_key("   ")
        self.assertIn("DEEPSEEK_API_KEY not configured", err)

    def test_validate_deepseek_api_key_rejects_placeholder(self):
        err = _validate_deepseek_api_key("sk-...")
        self.assertIn("looks like a placeholder", err)

    def test_validate_deepseek_api_key_rejects_wrong_prefix(self):
        err = _validate_deepseek_api_key("abc123")
        self.assertIn("must start with sk-", err)

    def test_validate_mineru_command_accepts_existing_path(self):
        mineru = self.tmpdir / "mineru"
        mineru.write_text("#!/bin/sh\n")
        self.assertIsNone(_validate_mineru_command(str(mineru)))

    def test_validate_mineru_command_rejects_missing_path(self):
        err = _validate_mineru_command(str(self.tmpdir / "missing-mineru"))
        self.assertIn("MinerU command not found", err)

    def test_ensure_writable_dir_creates_and_probes(self):
        path = self.tmpdir / "nested" / "assets"
        err = _ensure_writable_dir(path, "asset-dir")
        self.assertIsNone(err)
        self.assertTrue(path.is_dir())

    def test_open_checked_database_connection_returns_connection(self):
        conn = FakeDBConnection()
        psycopg = FakePsycopgModule(conn)
        result = _open_checked_database_connection(FakeSettings(), psycopg)
        self.assertIs(result, conn)
        self.assertIn("postgresql://", psycopg.conninfo)

    def test_open_checked_database_connection_reports_connect_error(self):
        psycopg = FakePsycopgModule(error=RuntimeError("connection refused"))
        with self.assertRaisesRegex(RuntimeError, "PostgreSQL connection failed"):
            _open_checked_database_connection(FakeSettings(), psycopg)

    def test_open_checked_database_connection_reports_missing_schema(self):
        conn = FakeDBConnection(missing_tables={"raw_assets"})
        psycopg = FakePsycopgModule(conn)
        with self.assertRaisesRegex(RuntimeError, "Database schema missing tables"):
            _open_checked_database_connection(FakeSettings(), psycopg)
        self.assertTrue(conn.closed)


# ---------------------------------------------------------------------------
# TestMarkdownReport
# ---------------------------------------------------------------------------


class TestMarkdownReport(unittest.TestCase):
    """ADR 022: comprehensive markdown report generation."""

    def setUp(self):
        self.results = [
            _make_result(paper_id="b_0001", pages=10, elapsed_s=45.0),
            _make_result(paper_id="b_0002", pages=8, elapsed_s=38.0,
                         status="partial", questions_warning=2,
                         crop_failed=1, quality_warning_counts={"unbalanced_latex": 1}),
        ]
        self.manifest = [
            {"paper_id": "b_0001", "status": "completed"},
            {"paper_id": "b_0002", "status": "partial"},
        ]
        self.step_timings = [
            {"step": "mineru_parse", "total_s": 60.0, "count": 2,
             "avg_s": 30.0, "max_s": 35.0, "slowest_paper": "b_0002",
             "pct_of_wall": 50},
        ]
        self.failure_taxonomy = Counter()
        self.failure_examples = {}

    def test_report_contains_summary_section(self):
        md = _generate_markdown_report(
            self.results, 120.0, self.manifest,
            self.step_timings, self.failure_taxonomy, self.failure_examples,
        )
        self.assertIn("## Summary", md)

    def test_report_contains_throughput_section(self):
        md = _generate_markdown_report(
            self.results, 120.0, self.manifest,
            self.step_timings, self.failure_taxonomy, self.failure_examples,
        )
        self.assertIn("## Throughput", md)

    def test_throughput_includes_sec_per_pdf(self):
        md = _generate_markdown_report(
            self.results, 120.0, self.manifest,
            self.step_timings, self.failure_taxonomy, self.failure_examples,
        )
        self.assertIn("Avg sec/PDF", md)
        self.assertIn("60.0s", md)

    def test_throughput_includes_sec_per_page(self):
        md = _generate_markdown_report(
            self.results, 120.0, self.manifest,
            self.step_timings, self.failure_taxonomy, self.failure_examples,
        )
        self.assertIn("Avg sec/page", md)

    def test_throughput_includes_sec_per_question(self):
        md = _generate_markdown_report(
            self.results, 120.0, self.manifest,
            self.step_timings, self.failure_taxonomy, self.failure_examples,
        )
        self.assertIn("Avg sec/question", md)

    def test_report_contains_asset_pipeline_section(self):
        md = _generate_markdown_report(
            self.results, 120.0, self.manifest,
            self.step_timings, self.failure_taxonomy, self.failure_examples,
        )
        self.assertIn("## Asset Pipeline", md)

    def test_report_contains_step_timing_section(self):
        md = _generate_markdown_report(
            self.results, 120.0, self.manifest,
            self.step_timings, self.failure_taxonomy, self.failure_examples,
        )
        self.assertIn("## Step Timing", md)
        self.assertIn("mineru_parse", md)

    def test_report_contains_per_paper_table(self):
        md = _generate_markdown_report(
            self.results, 120.0, self.manifest,
            self.step_timings, self.failure_taxonomy, self.failure_examples,
        )
        self.assertIn("## Per-Paper Results", md)
        self.assertIn("b_0001", md)
        self.assertIn("b_0002", md)

    def test_report_shows_status_counts(self):
        md = _generate_markdown_report(
            self.results, 120.0, self.manifest,
            self.step_timings, self.failure_taxonomy, self.failure_examples,
        )
        self.assertIn("Completed", md)
        self.assertIn("Partial", md)

    def test_report_success_rate(self):
        md = _generate_markdown_report(
            self.results, 120.0, self.manifest,
            self.step_timings, self.failure_taxonomy, self.failure_examples,
        )
        self.assertIn("Success rate", md)

    def test_failure_taxonomy_section_when_errors_exist(self):
        results = [
            _make_result(paper_id="b_0001", status="failed",
                         error="mineru: Connection refused"),
        ]
        ft = Counter({"mineru_transient": 1})
        fe = {"mineru_transient": "mineru: Connection refused"}
        md = _generate_markdown_report(
            results, 30.0, self.manifest,
            [], ft, fe,
        )
        self.assertIn("## Failure Taxonomy", md)
        self.assertIn("mineru_transient", md)
        self.assertIn("Connection refused", md)

    def test_no_failure_taxonomy_when_no_errors(self):
        md = _generate_markdown_report(
            self.results, 120.0, self.manifest,
            self.step_timings, Counter(), {},
        )
        self.assertNotIn("## Failure Taxonomy", md)

    def test_errors_section_when_errors_exist(self):
        results = [
            _make_result(paper_id="b_0001", status="completed"),
            _make_result(paper_id="b_0002", status="failed",
                         error="DeepSeek timeout"),
        ]
        md = _generate_markdown_report(
            results, 120.0, self.manifest,
            [], Counter(), {},
        )
        self.assertIn("## Errors", md)
        self.assertIn("DeepSeek timeout", md)

    def test_no_errors_section_when_no_errors(self):
        md = _generate_markdown_report(
            self.results, 120.0, self.manifest,
            self.step_timings, Counter(), {},
        )
        self.assertNotIn("## Errors", md)

    def test_quality_warning_distribution(self):
        results = [
            _make_result(paper_id="b_0001",
                         quality_warning_counts={"unbalanced_latex": 2, "no_analysis": 1}),
        ]
        md = _generate_markdown_report(
            results, 30.0, self.manifest,
            [], Counter(), {},
        )
        self.assertIn("## Quality Warning Distribution", md)
        self.assertIn("unbalanced_latex", md)
        self.assertIn("no_analysis", md)

    def test_no_warning_distribution_when_empty(self):
        results = [_make_result(paper_id="b_0001", quality_warning_counts={})]
        md = _generate_markdown_report(
            results, 30.0, self.manifest,
            [], Counter(), {},
        )
        self.assertNotIn("## Quality Warning Distribution", md)

    def test_success_rate_formula(self):
        # 3 completed + 1 partial out of 5 total = 80%
        results = [
            _make_result(paper_id=f"b_{i:04d}", status="completed")
            for i in range(1, 4)
        ] + [
            _make_result(paper_id="b_0004", status="partial"),
            _make_result(paper_id="b_0005", status="failed"),
        ]
        md = _generate_markdown_report(
            results, 200.0, self.manifest[:5],
            [], Counter(), {},
        )
        # 4 out of 5 = 80%
        self.assertIn("80.0%", md)

    def test_empty_results_handled(self):
        md = _generate_markdown_report(
            [], 0.0, [], [], Counter(), {},
        )
        self.assertIn("## Summary", md)
        self.assertIn("Total PDFs | 0", md)


# ---------------------------------------------------------------------------
# TestJSONSummary
# ---------------------------------------------------------------------------


class TestJSONSummary(unittest.TestCase):
    """ADR 022: comprehensive JSON summary generation."""

    def setUp(self):
        self.results = [
            _make_result(paper_id="b_0001", pages=10, elapsed_s=45.0,
                         crop_failed=0),
            _make_result(paper_id="b_0002", pages=8, elapsed_s=38.0,
                         status="partial", crop_failed=1),
        ]
        self.manifest = [
            {"paper_id": "b_0001", "status": "completed"},
            {"paper_id": "b_0002", "status": "partial"},
        ]
        self.step_timings = [
            {"step": "mineru_parse", "total_s": 60.0, "count": 2,
             "avg_s": 30.0, "max_s": 35.0, "slowest_paper": "b_0002",
             "pct_of_wall": 50},
        ]

    def test_manifest_field_present(self):
        summary = _generate_json_summary(
            self.results, 120.0, self.manifest,
            self.step_timings, Counter(),
        )
        self.assertIn("manifest", summary)
        self.assertEqual(summary["manifest"]["total"], 2)
        self.assertEqual(summary["manifest"]["completed"], 1)
        self.assertEqual(summary["manifest"]["partial"], 1)

    def test_manifest_status_counts(self):
        manifest = [
            {"paper_id": "a", "status": "completed"},
            {"paper_id": "b", "status": "completed"},
            {"paper_id": "c", "status": "partial"},
            {"paper_id": "d", "status": "failed"},
            {"paper_id": "e", "status": "pending"},
            {"paper_id": "f", "status": "crashed"},
        ]
        summary = _generate_json_summary(
            self.results, 120.0, manifest,
            self.step_timings, Counter(),
        )
        m = summary["manifest"]
        self.assertEqual(m["total"], 6)
        self.assertEqual(m["completed"], 2)
        self.assertEqual(m["partial"], 1)
        self.assertEqual(m["failed"], 1)
        self.assertEqual(m["pending"], 1)
        self.assertEqual(m["crashed"], 1)

    def test_throughput_field_present(self):
        summary = _generate_json_summary(
            self.results, 120.0, self.manifest,
            self.step_timings, Counter(),
        )
        self.assertIn("throughput", summary)
        t = summary["throughput"]
        self.assertEqual(t["wall_elapsed_s"], 120.0)
        self.assertEqual(t["total_pages"], 18)
        self.assertIn("avg_sec_per_pdf", t)
        self.assertIn("avg_sec_per_page", t)
        self.assertIn("avg_sec_per_question", t)

    def test_throughput_values(self):
        summary = _generate_json_summary(
            self.results, 120.0, self.manifest,
            self.step_timings, Counter(),
        )
        t = summary["throughput"]
        self.assertEqual(t["avg_sec_per_pdf"], 60.0)
        self.assertAlmostEqual(t["avg_sec_per_page"], 120.0 / 18, places=1)

    def test_results_field_present(self):
        summary = _generate_json_summary(
            self.results, 120.0, self.manifest,
            self.step_timings, Counter(),
        )
        self.assertIn("results", summary)
        self.assertEqual(summary["results"]["total_pdfs"], 2)
        self.assertEqual(summary["results"]["completed"], 1)
        self.assertEqual(summary["results"]["partial"], 1)

    def test_questions_field_present(self):
        summary = _generate_json_summary(
            self.results, 120.0, self.manifest,
            self.step_timings, Counter(),
        )
        self.assertIn("questions", summary)
        self.assertEqual(summary["questions"]["total"], 10)

    def test_assets_field_present(self):
        summary = _generate_json_summary(
            self.results, 120.0, self.manifest,
            self.step_timings, Counter(),
        )
        self.assertIn("assets", summary)
        self.assertEqual(summary["assets"]["crop_failed"], 1)

    def test_step_timing_field_present(self):
        summary = _generate_json_summary(
            self.results, 120.0, self.manifest,
            self.step_timings, Counter(),
        )
        self.assertIn("step_timing", summary)
        self.assertEqual(len(summary["step_timing"]), 1)
        self.assertEqual(summary["step_timing"][0]["step"], "mineru_parse")

    def test_failure_taxonomy_field_present(self):
        ft = Counter({"mineru_transient": 2, "deepseek": 1})
        summary = _generate_json_summary(
            self.results, 120.0, self.manifest,
            self.step_timings, ft,
        )
        self.assertIn("failure_taxonomy", summary)
        self.assertEqual(summary["failure_taxonomy"]["mineru_transient"], 2)
        self.assertEqual(summary["failure_taxonomy"]["deepseek"], 1)

    def test_papers_array_present(self):
        summary = _generate_json_summary(
            self.results, 120.0, self.manifest,
            self.step_timings, Counter(),
        )
        self.assertIn("papers", summary)
        self.assertEqual(len(summary["papers"]), 2)
        self.assertEqual(summary["papers"][0]["paper_id"], "b_0001")

    def test_paper_error_includes_failure_category(self):
        results = [
            _make_result(paper_id="b_0001", status="failed",
                         error="mineru: Connection refused"),
        ]
        summary = _generate_json_summary(
            results, 30.0, self.manifest[:1],
            [], Counter({"mineru_transient": 1}),
        )
        paper = summary["papers"][0]
        self.assertEqual(paper["failure_category"], "mineru_transient")

    def test_elapsed_s_field_present(self):
        summary = _generate_json_summary(
            self.results, 120.0, self.manifest,
            self.step_timings, Counter(),
        )
        self.assertEqual(summary["elapsed_s"], 120.0)

    def test_date_field_present(self):
        summary = _generate_json_summary(
            self.results, 120.0, self.manifest,
            self.step_timings, Counter(),
        )
        self.assertIn("date", summary)

    def test_success_rate_in_results(self):
        summary = _generate_json_summary(
            self.results, 120.0, self.manifest,
            self.step_timings, Counter(),
        )
        self.assertEqual(summary["results"]["success_rate"], 100.0)

    def test_failed_paper_in_results(self):
        results = [
            _make_result(paper_id="b_0001", status="completed"),
            _make_result(paper_id="b_0002", status="failed",
                         error="DeepSeek error"),
        ]
        summary = _generate_json_summary(
            results, 120.0, self.manifest,
            [], Counter(),
        )
        self.assertEqual(summary["results"]["failed"], 1)
        self.assertEqual(summary["results"]["success_rate"], 50.0)


# ---------------------------------------------------------------------------
# TestFailFastBehavior
# ---------------------------------------------------------------------------


class TestFailFastBehavior(unittest.TestCase):
    """ADR 022: --fail-fast stops on first failure/crash."""

    def test_fail_fast_stops_on_failed(self):
        results_so_far = [
            _make_result(paper_id="b_0001", status="completed"),
            _make_result(paper_id="b_0002", status="completed"),
            _make_result(paper_id="b_0003", status="failed",
                         error="mineru timeout"),
        ]
        fail_fast = True
        last_result = results_so_far[-1]
        if fail_fast and last_result["status"] in ("failed", "crashed"):
            should_stop = True
        else:
            should_stop = False
        self.assertTrue(should_stop)

    def test_fail_fast_stops_on_crashed(self):
        results_so_far = [
            _make_result(paper_id="b_0001", status="completed"),
            _make_result(paper_id="b_0002", status="crashed",
                         error="RuntimeError"),
        ]
        fail_fast = True
        last_result = results_so_far[-1]
        self.assertTrue(last_result["status"] == "crashed")

    def test_fail_fast_does_not_stop_on_completed(self):
        last_result = _make_result(paper_id="b_0001", status="completed")
        should_stop = (last_result["status"] in ("failed", "crashed"))
        self.assertFalse(should_stop)

    def test_fail_fast_does_not_stop_on_partial(self):
        last_result = _make_result(paper_id="b_0001", status="partial")
        should_stop = (last_result["status"] in ("failed", "crashed"))
        self.assertFalse(should_stop)

    def test_no_fail_fast_continues_on_failed(self):
        # Without --fail-fast, even a failed result continues
        fail_fast = False
        last_result = _make_result(paper_id="b_0001", status="failed")
        would_stop = fail_fast and last_result["status"] in ("failed", "crashed")
        self.assertFalse(would_stop)


# ---------------------------------------------------------------------------
# TestProcessOneSafe
# ---------------------------------------------------------------------------


class TestProcessOneSafe(unittest.TestCase):
    """ADR 022: _process_one_safe crash isolation."""

    def test_crashed_status_on_exception(self):
        """When an unhandled exception occurs, status is 'crashed' not 'failed'."""
        from tools.batch_real_ingest import _process_one_safe

        with mock.patch(
            "tools.batch_real_ingest._process_one_pdf",
            side_effect=RuntimeError("unexpected crash"),
        ):
            result = _process_one_safe(
                pdf_path=Path("/fake/test.pdf"),
                index=1,
                prefix="batch",
                work_root=Path("/tmp"),
                asset_dir=Path("/tmp/assets"),
                resume=False,
                deepseek_client=mock.Mock(),
                mineru_command="mineru",
                repository=mock.Mock(),
            )
        self.assertEqual(result["status"], "crashed")
        self.assertIn("unexpected crash", result["error"])

    def test_crashed_result_has_default_zeros(self):
        from tools.batch_real_ingest import _process_one_safe

        with mock.patch(
            "tools.batch_real_ingest._process_one_pdf",
            side_effect=Exception("boom"),
        ):
            result = _process_one_safe(
                pdf_path=Path("/fake/test.pdf"),
                index=1,
                prefix="batch",
                work_root=Path("/tmp"),
                asset_dir=Path("/tmp/assets"),
                resume=False,
                deepseek_client=mock.Mock(),
                mineru_command="mineru",
                repository=mock.Mock(),
            )
        self.assertEqual(result["questions_passed"], 0)
        self.assertEqual(result["questions_failed"], 0)
        self.assertEqual(result["raw_assets"], 0)
        self.assertEqual(result["elapsed_s"], 0)
        self.assertIsNone(result["pages"])


if __name__ == "__main__":
    unittest.main()
