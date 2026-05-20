"""Tests for ADR 021: MinerU retry logic and resume artifact validation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from question_bank.services.mineru import (
    _is_transient_error,
    _discover_artifacts,
    LocalMinerURunner,
    MinerUResult,
)
from question_bank.services.paper_orchestrator import (
    _step_mineru_parse,
    _validate_resume_artifacts,
)


# ---------------------------------------------------------------------------
# TestTransientErrorClassification
# ---------------------------------------------------------------------------


class TestTransientErrorClassification(unittest.TestCase):
    """ADR 021: transient vs non-transient error classification."""

    def test_connection_refused_is_transient(self):
        self.assertTrue(_is_transient_error(
            "MinerU exited with code 1: Connection refused"
        ))

    def test_connection_reset_is_transient(self):
        self.assertTrue(_is_transient_error(
            "subprocess.CalledProcessError: Connection reset by peer"
        ))

    def test_connection_aborted_is_transient(self):
        self.assertTrue(_is_transient_error(
            "Connection aborted during handshake"
        ))

    def test_connection_attempts_failed_is_transient(self):
        self.assertTrue(_is_transient_error(
            "All connection attempts failed to localhost:8080"
        ))

    def test_timeout_is_transient(self):
        self.assertTrue(_is_transient_error(
            "Timed out while polling task status after 300s"
        ))

    def test_connect_timeout_is_transient(self):
        self.assertTrue(_is_transient_error(
            "connect timed out after 30 seconds"
        ))

    def test_read_timeout_is_transient(self):
        self.assertTrue(_is_transient_error(
            "Read timed out waiting for response"
        ))

    def test_dns_failure_is_transient(self):
        self.assertTrue(_is_transient_error(
            "Could not resolve host: api.local"
        ))

    def test_temporary_name_resolution_is_transient(self):
        self.assertTrue(_is_transient_error(
            "Temporary failure in name resolution"
        ))

    def test_broken_pipe_is_transient(self):
        self.assertTrue(_is_transient_error(
            "broken pipe during data transfer"
        ))

    def test_network_unreachable_is_transient(self):
        self.assertTrue(_is_transient_error(
            "Network is unreachable"
        ))

    def test_remote_end_closed_is_transient(self):
        self.assertTrue(_is_transient_error(
            "Remote end closed connection unexpectedly"
        ))

    def test_file_not_found_is_not_transient(self):
        self.assertFalse(_is_transient_error(
            "No such file or directory: /tmp/missing.pdf"
        ))

    def test_pdf_not_found_is_not_transient(self):
        self.assertFalse(_is_transient_error(
            "PDF file not found: /tmp/missing.pdf"
        ))

    def test_model_missing_is_not_transient(self):
        self.assertFalse(_is_transient_error(
            "Model download failed: model not found in registry"
        ))

    def test_model_with_caps_is_not_transient(self):
        self.assertFalse(_is_transient_error(
            "Model checkpoint missing: /models/v1.0/model.safetensors"
        ))

    def test_invalid_argument_is_not_transient(self):
        self.assertFalse(_is_transient_error(
            "invalid argument: --unknown-flag"
        ))

    def test_unknown_option_is_not_transient(self):
        self.assertFalse(_is_transient_error(
            "unknown option: --bad-arg"
        ))

    def test_permission_denied_is_not_transient(self):
        self.assertFalse(_is_transient_error(
            "Permission denied: cannot write to /root/"
        ))

    def test_cannot_open_is_not_transient(self):
        self.assertFalse(_is_transient_error(
            "Cannot open file: permission denied"
        ))

    def test_generic_error_is_not_transient(self):
        """Unknown errors should not be retried by default."""
        self.assertFalse(_is_transient_error(
            "some random error message that doesn't match any pattern"
        ))


# ---------------------------------------------------------------------------
# TestMinerURetryBehavior
# ---------------------------------------------------------------------------


class TestMinerURetryBehavior(unittest.TestCase):
    """ADR 021: MinerU retry loop behavior."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _out(self) -> Path:
        return self.tmpdir / "out"

    def test_success_on_first_attempt_no_retry(self):
        """First attempt succeeds → no retry."""
        runner = LocalMinerURunner(command="mineru", max_retries=2)
        with mock.patch("subprocess.run") as mock_run:
            with mock.patch(
                "question_bank.services.mineru._discover_artifacts",
                return_value=MinerUResult(
                    output_dir=self._out(),
                    markdown_path=self._out() / "test.md",
                    raw_json_path=self._out() / "test_content_list.json",
                ),
            ):
                result = runner.parse_pdf(
                    self.tmpdir / "test.pdf", self._out(),
                )
        self.assertEqual(mock_run.call_count, 1)
        self.assertIsNotNone(result.markdown_path)

    def test_transient_error_retried_then_succeeds(self):
        """First attempt transient failure → retry succeeds."""
        import subprocess
        runner = LocalMinerURunner(
            command="mineru", max_retries=2, retry_backoff_base=0.01,
        )
        call_count = [0]

        def fake_run(cmd, check=True):
            call_count[0] += 1
            if call_count[0] == 1:
                raise subprocess.CalledProcessError(1, cmd, output="Connection refused")
            # Second call succeeds

        with mock.patch("subprocess.run", side_effect=fake_run):
            with mock.patch("time.sleep"):
                with mock.patch(
                    "question_bank.services.mineru._discover_artifacts",
                    return_value=MinerUResult(
                        output_dir=self._out(),
                        markdown_path=self._out() / "test.md",
                        raw_json_path=self._out() / "test_content_list.json",
                    ),
                ):
                    result = runner.parse_pdf(
                        self.tmpdir / "test.pdf", self._out(),
                    )
        self.assertEqual(call_count[0], 2)  # 2 attempts
        self.assertIsNotNone(result.markdown_path)

    def test_non_transient_error_not_retried(self):
        """Non-transient error should NOT be retried."""
        import subprocess
        runner = LocalMinerURunner(
            command="mineru", max_retries=2, retry_backoff_base=0.01,
        )
        call_count = [0]

        def fake_run(cmd, check=True):
            call_count[0] += 1
            raise subprocess.CalledProcessError(
                1, cmd, output="No such file or directory: bad.pdf"
            )

        with mock.patch("subprocess.run", side_effect=fake_run):
            with mock.patch("time.sleep"):
                with self.assertRaises(RuntimeError) as ctx:
                    runner.parse_pdf(self.tmpdir / "test.pdf", self._out())
        self.assertIn("MinerU exited with code 1", str(ctx.exception))
        self.assertEqual(call_count[0], 1)  # only 1 attempt, no retry

    def test_max_retries_exhausted(self):
        """When all retries exhausted on transient error."""
        import subprocess
        runner = LocalMinerURunner(
            command="mineru", max_retries=2, retry_backoff_base=0.01,
        )
        call_count = [0]

        def fake_run(cmd, check=True):
            call_count[0] += 1
            raise subprocess.CalledProcessError(
                1, cmd, output="Connection refused (attempt {})".format(call_count[0])
            )

        with mock.patch("subprocess.run", side_effect=fake_run):
            with mock.patch("time.sleep"):
                with self.assertRaises(RuntimeError) as ctx:
                    runner.parse_pdf(self.tmpdir / "test.pdf", self._out())
        self.assertIn("failed after 3 attempts", str(ctx.exception))
        self.assertEqual(call_count[0], 3)  # original + 2 retries

    def test_retry_with_exponential_backoff(self):
        """Verify backoff delay increases exponentially."""
        import subprocess
        runner = LocalMinerURunner(
            command="mineru", max_retries=2, retry_backoff_base=30.0,
        )
        sleeps: list[float] = []
        call_count = [0]

        def fake_run(cmd, check=True):
            call_count[0] += 1
            if call_count[0] < 3:
                raise subprocess.CalledProcessError(1, cmd, output="Connection reset")
            # third succeeds

        def fake_sleep(t):
            sleeps.append(t)

        with mock.patch("subprocess.run", side_effect=fake_run):
            with mock.patch("time.sleep", side_effect=fake_sleep):
                with mock.patch(
                    "question_bank.services.mineru._discover_artifacts",
                    return_value=MinerUResult(
                        output_dir=self._out(),
                        markdown_path=self._out() / "test.md",
                        raw_json_path=self._out() / "test_content_list.json",
                    ),
                ):
                    runner.parse_pdf(self.tmpdir / "test.pdf", self._out())
        self.assertEqual(len(sleeps), 2)
        self.assertAlmostEqual(sleeps[0], 30.0, delta=1.0)
        self.assertAlmostEqual(sleeps[1], 60.0, delta=1.0)


# ---------------------------------------------------------------------------
# TestResumeArtifactValidation
# ---------------------------------------------------------------------------


def _make_mini_json(mineru_elements: list[dict]) -> str:
    """Helper: produce a JSON file that _load_layout_elements() can consume."""
    return json.dumps(mineru_elements)


class TestResumeArtifactValidation(unittest.TestCase):
    """ADR 021: resume artifact validity checks."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_valid_artifacts_pass_validation(self):
        md = self.tmpdir / "test.md"
        md.write_text("# Question 1\n\nSolve for x.")
        js = self.tmpdir / "test.json"
        js.write_text(_make_mini_json([
            {"id": "m000001", "page": 1, "type": "text",
             "bbox": [0.1, 0.1, 0.3, 0.3], "text": "solve"}
        ]))
        self.assertTrue(_validate_resume_artifacts(md, js))

    def test_empty_markdown_fails_validation(self):
        md = self.tmpdir / "empty.md"
        md.write_text("")
        js = self.tmpdir / "test.json"
        js.write_text(_make_mini_json([
            {"id": "m000001", "page": 1, "type": "text",
             "bbox": [0.1, 0.1, 0.3, 0.3], "text": "x"}
        ]))
        self.assertFalse(_validate_resume_artifacts(md, js))

    def test_whitespace_only_markdown_fails(self):
        md = self.tmpdir / "ws.md"
        md.write_text("   \n  \n  ")
        js = self.tmpdir / "test.json"
        js.write_text(_make_mini_json([
            {"id": "m000001", "page": 1, "type": "text",
             "bbox": [0.1, 0.1, 0.3, 0.3], "text": "x"}
        ]))
        self.assertFalse(_validate_resume_artifacts(md, js))

    def test_markdown_read_error_fails(self):
        """If markdown file can't be read, validation fails."""
        md = self.tmpdir / "bad.md"
        # Don't create the file
        js = self.tmpdir / "test.json"
        js.write_text(_make_mini_json([
            {"id": "m000001", "page": 1, "type": "text",
             "bbox": [0.1, 0.1, 0.3, 0.3], "text": "x"}
        ]))
        self.assertFalse(_validate_resume_artifacts(md, js))

    def test_unparseable_json_fails(self):
        md = self.tmpdir / "test.md"
        md.write_text("# Question 1")
        js = self.tmpdir / "bad.json"
        js.write_text("this is not json {{{")
        self.assertFalse(_validate_resume_artifacts(md, js))

    def test_empty_json_array_fails(self):
        """Empty elements array → no layout elements → fail."""
        md = self.tmpdir / "test.md"
        md.write_text("# Question 1")
        js = self.tmpdir / "empty.json"
        js.write_text("[]")
        self.assertFalse(_validate_resume_artifacts(md, js))

    def test_json_with_zero_elements_after_load_fails(self):
        """JSON that parses but has no valid elements after _load_layout_elements."""
        md = self.tmpdir / "test.md"
        md.write_text("# Question 1")
        js = self.tmpdir / "corrupt.json"
        # This is parseable JSON but _load_layout_elements will reject it
        js.write_text('[{"not_a_valid_element": true}]')
        self.assertFalse(_validate_resume_artifacts(md, js))

    def test_truncated_json_fails(self):
        md = self.tmpdir / "test.md"
        md.write_text("# Question 1")
        js = self.tmpdir / "truncated.json"
        js.write_text('[{"id": "m000001", "page": 1, "type": "text"')
        self.assertFalse(_validate_resume_artifacts(md, js))


# ---------------------------------------------------------------------------
# TestArtifactDiscovery
# ---------------------------------------------------------------------------


class TestArtifactDiscovery(unittest.TestCase):
    """ADR 021: artifact discovery after successful MinerU run."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_discovers_markdown_and_content_list_json(self):
        pdf_stem = "paper"
        (self.tmpdir / f"{pdf_stem}.md").write_text("# test")
        (self.tmpdir / f"{pdf_stem}_content_list.json").write_text("[]")
        result = _discover_artifacts(self.tmpdir, pdf_stem)
        self.assertIsNotNone(result.markdown_path)
        self.assertIsNotNone(result.raw_json_path)
        self.assertIn("content_list.json", str(result.raw_json_path))

    def test_falls_back_to_middle_json(self):
        pdf_stem = "paper"
        (self.tmpdir / f"{pdf_stem}.md").write_text("# test")
        (self.tmpdir / f"{pdf_stem}_middle.json").write_text("[]")
        result = _discover_artifacts(self.tmpdir, pdf_stem)
        self.assertIn("middle.json", str(result.raw_json_path))

    def test_falls_back_to_any_json(self):
        pdf_stem = "paper"
        (self.tmpdir / f"{pdf_stem}.md").write_text("# test")
        (self.tmpdir / "other.json").write_text("[]")
        result = _discover_artifacts(self.tmpdir, pdf_stem)
        self.assertIsNotNone(result.raw_json_path)

    def test_no_artifacts_returns_none(self):
        pdf_stem = "paper"
        result = _discover_artifacts(self.tmpdir, pdf_stem)
        self.assertIsNone(result.markdown_path)
        self.assertIsNone(result.raw_json_path)


# ---------------------------------------------------------------------------
# TestStepMineruParseResume
# ---------------------------------------------------------------------------


class TestStepMineruParseResume(unittest.TestCase):
    """ADR 021: _step_mineru_parse resume behavior with validation."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        if self.tmpdir.exists():
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_resume_skips_when_valid_artifacts_exist(self):
        """When valid artifacts exist, step returns skipped."""
        work_dir = self.tmpdir / "work"
        work_dir.mkdir()
        (work_dir / "test.md").write_text("# Question 1\n\nSolve for $x$.")
        (work_dir / "test_content_list.json").write_text(
            _make_mini_json([
                {"id": "m000001", "page": 1, "type": "text",
                 "bbox": [0.1, 0.1, 0.3, 0.3], "text": "solve"}
            ])
        )
        # The PDF path doesn't matter since resume should skip
        ctx: dict = {}
        result = _step_mineru_parse(
            paper_id="test_001", pdf_path="/fake/test.pdf",
            work_dir=str(work_dir), resume=True,
            mineru_command="mineru", ctx=ctx,
        )
        self.assertEqual(result.status, "skipped")
        self.assertIn("mineru_result", ctx)

    def test_resume_reruns_when_artifacts_corrupt(self):
        """When artifacts are corrupt, step runs MinerU instead of skipping."""
        import subprocess
        work_dir = self.tmpdir / "work"
        work_dir.mkdir()
        # Empty markdown file
        (work_dir / "test.md").write_text("")
        (work_dir / "test_content_list.json").write_text("[]")  # empty = no elements

        ctx: dict = {}
        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner.parse_pdf",
            return_value=MinerUResult(
                output_dir=work_dir,
                markdown_path=work_dir / "test.md",
                raw_json_path=work_dir / "test_content_list.json",
            ),
        ) as mock_parse:
            result = _step_mineru_parse(
                paper_id="test_001", pdf_path="/fake/test.pdf",
                work_dir=str(work_dir), resume=True,
                mineru_command="mineru", ctx=ctx,
            )
        self.assertEqual(result.status, "success")
        mock_parse.assert_called_once()

    def test_resume_reruns_when_json_unparseable(self):
        """When JSON is unparseable, rerun MinerU."""
        work_dir = self.tmpdir / "work"
        work_dir.mkdir()
        (work_dir / "test.md").write_text("# Question 1")
        (work_dir / "test.json").write_text("not json {{{")

        ctx: dict = {}
        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner.parse_pdf",
            return_value=MinerUResult(
                output_dir=work_dir,
                markdown_path=work_dir / "test.md",
                raw_json_path=work_dir / "test_content_list.json",
            ),
        ) as mock_parse:
            result = _step_mineru_parse(
                paper_id="test_001", pdf_path="/fake/test.pdf",
                work_dir=str(work_dir), resume=True,
                mineru_command="mineru", ctx=ctx,
            )
        self.assertEqual(result.status, "success")
        mock_parse.assert_called_once()

    def test_resume_reruns_when_no_json_files(self):
        """When no JSON files exist, even with md, rerun MinerU."""
        work_dir = self.tmpdir / "work"
        work_dir.mkdir()
        (work_dir / "test.md").write_text("# Question 1")

        ctx: dict = {}
        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner.parse_pdf",
            return_value=MinerUResult(
                output_dir=work_dir,
                markdown_path=work_dir / "test.md",
                raw_json_path=work_dir / "test_content_list.json",
            ),
        ) as mock_parse:
            result = _step_mineru_parse(
                paper_id="test_001", pdf_path="/fake/test.pdf",
                work_dir=str(work_dir), resume=True,
                mineru_command="mineru", ctx=ctx,
            )
        self.assertEqual(result.status, "success")
        mock_parse.assert_called_once()


if __name__ == "__main__":
    unittest.main()
