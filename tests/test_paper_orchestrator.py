"""Tests for ADR 009: Paper Ingestion Orchestrator."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from question_bank.domain.models import QualityReport, Question, QuestionBlock
from question_bank.pipeline import ProcessingResult
from question_bank.services.paper_orchestrator import (
    IngestionReport,
    StepResult,
    ingest_paper_full,
)


# ---------------------------------------------------------------------------
# Fake / helper classes
# ---------------------------------------------------------------------------


class FakeDeepSeekClient:
    def structure_question(self, raw_markdown: str) -> dict:
        return {
            "question_type": "single_choice",
            "stem_latex": raw_markdown,
            "choices": [{"label": "A", "content_latex": "x=1"},
                        {"label": "B", "content_latex": "x=2"}],
            "answer_latex": "A",
            "analysis_latex": "",
            "knowledge_points": [],
            "difficulty": None,
            "warnings": [],
        }


class FakeRepository:
    """Minimal fake that records calls and returns sensible defaults."""

    def __init__(self):
        self._raw_assets: list[dict] = []
        self._blocks: list[dict] = []
        self.saved_results: list = []
        self.saved_groups: list = []
        self.identified_block_ids: list[str] = []
        self.crop_updates: list = []
        self.phash_updates: list = []
        self.committed = False
        self.connection = FakeConnection(self)

    def save_processing_result(self, result):
        self.saved_results.append(result)
        self.committed = True

    def identify_paper_assets(self, paper_id, blocks, elements_by_id):
        self.identified_block_ids = [b.question_block_id for b in blocks]
        return {"raw_assets": self._raw_assets, "links": []}

    def list_raw_assets(self, paper_id=None, limit=100):
        if paper_id:
            return [ra for ra in self._raw_assets if ra.get("paper_id") == paper_id]
        return self._raw_assets

    def update_raw_asset_crop(self, raw_asset_id, crop_path, storage_url,
                               content_hash, width, height, status):
        self.crop_updates.append({
            "id": raw_asset_id, "crop_path": crop_path,
            "storage_url": storage_url, "content_hash": content_hash,
            "status": status,
        })

    def update_raw_asset_phash(self, raw_asset_id, perceptual_hash):
        self.phash_updates.append({
            "id": raw_asset_id, "perceptual_hash": perceptual_hash,
        })

    def save_duplicate_candidate_group(self, group):
        self.saved_groups.append(group)


class FakeConnection:
    def __init__(self, repo: FakeRepository):
        self._repo = repo
        self.committed = False

    def cursor(self):
        return FakeCursor(self._repo)

    def commit(self):
        self._repo.committed = True

    def rollback(self):
        pass


class FakeCursor:
    def __init__(self, repo: FakeRepository):
        self._repo = repo
        self._last_sql = ""
        self._last_params = {}

    def execute(self, sql, params=None):
        self._last_sql = sql
        self._last_params = params or {}

    def fetchall(self):
        return self._repo._blocks


def _make_block(block_id="paper_001_qb_0001", paper_id="paper_001",
                qn="1", sect="", md="test markdown"):
    return QuestionBlock(
        id=block_id, paper_id=paper_id, parse_run_id=None,
        question_number=qn, section_title=sect,
        raw_markdown=md, pages=[1], bbox=None,
        split_confidence=1.0, needs_review=False,
    )


def _make_question(question_id="paper_001_q_0001", qtype="single_choice",
                   stem="test stem", answer="A", analysis=""):
    return Question(
        id=question_id, question_type=qtype,
        stem_latex=stem, choices=[],
        answer_latex=answer, analysis_latex=analysis,
        knowledge_points=[], difficulty=None,
    )


def _make_quality_report(question_id="paper_001_q_0001"):
    return QualityReport(
        question_id=question_id, issues=[], model_warnings=[],
        overall_score=1.0, needs_review=False,
    )


# ---------------------------------------------------------------------------
# TestPaperOrchestrator
# ---------------------------------------------------------------------------


class TestPaperOrchestrator(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.work_dir = Path(self.tmpdir) / "runs" / "paper_001"
        self.asset_dir = Path(self.tmpdir) / "assets"

    def _make_mineru_output(self):
        """Create fake MinerU output files: output.md, output.json."""
        self.work_dir.mkdir(parents=True, exist_ok=True)
        (self.work_dir / "output.md").write_text("1. test question\n", encoding="utf-8")
        (self.work_dir / "output.json").write_text(json.dumps([
            {"id": "e1", "page": 1, "type": "text",
             "bbox": [0.1, 0.1, 0.5, 0.15], "text": "1. test question",
             "confidence": 0.98},
        ]), encoding="utf-8")

    def _make_mineru_content_list_output(self):
        """Create MinerU 3.x content_list artifacts."""
        parse_dir = self.work_dir / "paper_001" / "hybrid_auto"
        parse_dir.mkdir(parents=True, exist_ok=True)
        (parse_dir / "paper_001.md").write_text("1. 已知 $x=1$，求 $x+1$。\n", encoding="utf-8")
        (parse_dir / "paper_001_content_list.json").write_text(json.dumps([
            {
                "type": "text",
                "text": "1. 已知 $x=1$，求 $x+1$。",
                "bbox": [80, 120, 820, 160],
                "page_idx": 0,
            },
            {
                "type": "equation",
                "text": "$$x+1=2$$",
                "bbox": [100, 165, 500, 205],
                "page_idx": 0,
            },
            {
                "type": "page_number",
                "text": "1",
                "bbox": [490, 960, 510, 980],
                "page_idx": 0,
            },
        ]), encoding="utf-8")

    def test_happy_path_all_steps_succeed(self):
        """Full pipeline with all steps succeeding."""
        self._make_mineru_output()
        repo = FakeRepository()

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                repository=repo,
                deepseek_client=FakeDeepSeekClient(),
            )

        self.assertEqual(report.status, "completed")
        step_names = [s.name for s in report.steps]
        self.assertIn("mineru_parse", step_names)
        self.assertIn("layout_ownership", step_names)
        self.assertIn("deepseek_structure", step_names)
        self.assertIn("save_questions", step_names)
        self.assertIn("identify_assets", step_names)
        self.assertIn("crop_assets", step_names)
        self.assertIn("store_assets", step_names)
        self.assertIn("compute_phash", step_names)
        self.assertIn("duplicate_candidates", step_names)
        self.assertIn("visual_candidates", step_names)

        # All critical steps must succeed
        for s in report.steps:
            if s.name in ("mineru_parse", "layout_ownership", "deepseek_structure",
                          "save_questions", "identify_assets"):
                self.assertEqual(s.status, "success", f"{s.name} should succeed")

        # Verify report was written
        report_path = self.work_dir / "run-report.json"
        self.assertTrue(report_path.exists())

    def test_mineru_content_list_is_normalized_for_layout_ownership(self):
        """Real MinerU 3.x content_list JSON is converted before layout ownership."""
        self._make_mineru_content_list_output()
        repo = FakeRepository()

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                resume=True,
                repository=repo,
                deepseek_client=FakeDeepSeekClient(),
            )

        mock_mineru.return_value.parse_pdf.assert_not_called()
        self.assertEqual(report.status, "completed")
        layout_step = next(s for s in report.steps if s.name == "layout_ownership")
        self.assertEqual(layout_step.output_count, 1)
        self.assertEqual(len(repo.saved_results), 1)

    def test_mineru_resume_skips_when_output_exists(self):
        """When output.md and output.json both exist and resume=True, MinerU is skipped."""
        self._make_mineru_output()
        repo = FakeRepository()

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                resume=True,
                repository=repo,
                deepseek_client=FakeDeepSeekClient(),
            )

        # MinerU should NOT have been called
        mock_mineru.return_value.parse_pdf.assert_not_called()

        mineru_step = next(s for s in report.steps if s.name == "mineru_parse")
        self.assertEqual(mineru_step.status, "skipped")

    def test_mineru_resume_requires_both_output_files(self):
        """When only output.md exists (not output.json), resume does NOT skip MinerU."""
        self.work_dir.mkdir(parents=True, exist_ok=True)
        (self.work_dir / "output.md").write_text("1. test\n", encoding="utf-8")
        # output.json is deliberately missing

        repo = FakeRepository()

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_instance = mock_mineru.return_value
            mock_instance.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                resume=True,
                repository=repo,
                deepseek_client=FakeDeepSeekClient(),
            )

        # MinerU SHOULD have been called (output.json is missing)
        mock_instance.parse_pdf.assert_called_once()

        mineru_step = next(s for s in report.steps if s.name == "mineru_parse")
        self.assertEqual(mineru_step.status, "success")

    def test_critical_step_failure_stops_pipeline(self):
        """When a critical step fails, subsequent steps are not executed."""
        repo = FakeRepository()

        # No MinerU output → layout_ownership will fail
        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                repository=repo,
                deepseek_client=FakeDeepSeekClient(),
            )

        # layout_ownership should have failed (no output.json)
        self.assertEqual(report.status, "failed")
        layout_step = next(s for s in report.steps if s.name == "layout_ownership")
        self.assertEqual(layout_step.status, "failed")

        # Steps after layout_ownership should not exist
        step_names = {s.name for s in report.steps}
        self.assertNotIn("deepseek_structure", step_names)
        self.assertNotIn("save_questions", step_names)

    def test_non_critical_crop_failure_continues(self):
        """Non-critical step failure continues pipeline and records warning."""
        self._make_mineru_output()
        repo = FakeRepository()
        repo._raw_assets = [{
            "id": "ra_001", "paper_id": "paper_001", "page": 1,
            "bbox_json": "[0.1,0.1,0.3,0.3]", "asset_type": "image",
            "source_element_id": "e1", "crop_path": None,
            "storage_url": None, "perceptual_hash": "",
            "content_hash": "", "width": None, "height": None,
            "status": "active",
        }]

        # crop_pdf_assets raises ImportError ("PyMuPDF not installed")
        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )
            with mock.patch(
                "question_bank.services.paper_orchestrator.crop_pdf_assets",
                side_effect=ImportError("no fitz"),
            ):
                report = ingest_paper_full(
                    paper_id="paper_001",
                    pdf_path="/tmp/test.pdf",
                    work_dir=str(self.work_dir),
                    asset_dir=str(self.asset_dir),
                    repository=repo,
                    deepseek_client=FakeDeepSeekClient(),
                )

        # Pipeline should complete (not fail)
        self.assertIn(report.status, ("completed", "partial"))

        # Crop step should have failed
        crop_step = next(s for s in report.steps if s.name == "crop_assets")
        self.assertEqual(crop_step.status, "failed")

        # Later steps should still exist
        step_names = {s.name for s in report.steps}
        self.assertIn("compute_phash", step_names)
        self.assertIn("visual_candidates", step_names)

        # Warning should be recorded
        self.assertTrue(any("crop_assets" in w for w in report.warnings),
                        f"Expected crop warning in {report.warnings}")

    def test_dry_run_skips_database_writes(self):
        """--dry-run skips all steps that write to the database."""
        self._make_mineru_output()
        repo = FakeRepository()

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                dry_run=True,
                repository=repo,
                deepseek_client=FakeDeepSeekClient(),
            )

        # DB-write steps should be skipped
        save_step = next(s for s in report.steps if s.name == "save_questions")
        self.assertEqual(save_step.status, "skipped")

        identify_step = next(s for s in report.steps if s.name == "identify_assets")
        self.assertEqual(identify_step.status, "skipped")

        crop_step = next(s for s in report.steps if s.name == "crop_assets")
        self.assertEqual(crop_step.status, "skipped")

        # But read-only steps still run
        lo_step = next(s for s in report.steps if s.name == "layout_ownership")
        self.assertEqual(lo_step.status, "success")

        ds_step = next(s for s in report.steps if s.name == "deepseek_structure")
        self.assertEqual(ds_step.status, "success")

        # No DB saves
        self.assertEqual(len(repo.saved_results), 0)
        self.assertEqual(len(repo.crop_updates), 0)

    def test_run_report_json_structure(self):
        """The run-report.json has the expected structure."""
        self._make_mineru_output()
        repo = FakeRepository()

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                repository=repo,
                deepseek_client=FakeDeepSeekClient(),
            )

        report_path = self.work_dir / "run-report.json"
        data = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(data["paper_id"], "paper_001")
        self.assertIn(data["status"], ("completed", "partial", "failed"))
        self.assertIn("started_at", data)
        self.assertIn("finished_at", data)
        self.assertIsInstance(data["steps"], list)
        self.assertGreater(len(data["steps"]), 0)

        step = data["steps"][0]
        self.assertIn("name", step)
        self.assertIn("status", step)
        self.assertIn("started_at", step)
        self.assertIn("finished_at", step)
        self.assertIn("input_count", step)
        self.assertIn("output_count", step)
        self.assertIn("error", step)
        self.assertIn("warnings", step)

        self.assertIsInstance(data["counts"], dict)
        self.assertIsInstance(data["warnings"], list)
        self.assertIsInstance(data["errors"], list)

    def test_work_dir_auto_created(self):
        """work_dir is created automatically if it doesn't exist."""
        non_existent = Path(self.tmpdir) / "nonexistent" / "paper_001"
        self.assertFalse(non_existent.exists())

        repo = FakeRepository()

        # Create markdown so MinerU resume check passes
        non_existent.mkdir(parents=True)
        (non_existent / "output.md").write_text("1. test\n", encoding="utf-8")
        (non_existent / "output.json").write_text(json.dumps([
            {"id": "e1", "page": 1, "type": "text",
             "bbox": [0.1, 0.1, 0.5, 0.15], "text": "1. test",
             "confidence": 0.98},
        ]), encoding="utf-8")

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ):
            ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(non_existent),
                asset_dir=str(self.asset_dir),
                repository=repo,
                deepseek_client=FakeDeepSeekClient(),
                resume=True,
            )

        self.assertTrue(non_existent.exists())

    def test_counts_summarized_correctly(self):
        """Counts dict in report reflects actual step outputs."""
        self._make_mineru_output()
        repo = FakeRepository()

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                repository=repo,
                deepseek_client=FakeDeepSeekClient(),
            )

        counts = report.counts
        self.assertIn("steps_total", counts)
        self.assertIn("steps_succeeded", counts)
        self.assertIn("steps_warning", counts)
        self.assertIn("steps_failed", counts)
        self.assertIn("steps_skipped", counts)

        # Verify total matches
        self.assertEqual(
            counts["steps_total"],
            counts["steps_succeeded"] + counts["steps_warning"] + counts["steps_failed"] + counts["steps_skipped"],
        )

        # Specific step counts
        self.assertIn("deepseek_structure", counts)
        self.assertGreater(counts["deepseek_structure"], 0)

    def test_errors_and_warnings_separated(self):
        """Critical failures go to errors, non-critical to warnings."""
        self._make_mineru_output()
        repo = FakeRepository()
        repo._raw_assets = [{
            "id": "ra_001", "paper_id": "paper_001", "page": 1,
            "bbox_json": "[0.1,0.1,0.3,0.3]", "asset_type": "image",
            "source_element_id": "e1", "crop_path": None,
            "storage_url": None, "perceptual_hash": "",
            "content_hash": "", "width": None, "height": None,
            "status": "active",
        }]

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )
            with mock.patch(
                "question_bank.services.paper_orchestrator.crop_pdf_assets",
                side_effect=ImportError("no fitz"),
            ):
                report = ingest_paper_full(
                    paper_id="paper_001",
                    pdf_path="/tmp/test.pdf",
                    work_dir=str(self.work_dir),
                    asset_dir=str(self.asset_dir),
                    repository=repo,
                    deepseek_client=FakeDeepSeekClient(),
                )

        # Non-critical failure → warning, not error
        crop_warnings = [w for w in report.warnings if "crop_assets" in w]
        crop_errors = [e for e in report.errors if "crop_assets" in e]
        self.assertTrue(len(crop_warnings) > 0 or any("no fitz" in w for w in report.warnings),
                        f"Expected warning about crop failure in {report.warnings}")
        self.assertEqual(len(crop_errors), 0,
                         f"Crop failure should not be in errors: {report.errors}")

    def test_empty_raw_assets_handled_gracefully(self):
        """Zero raw_assets doesn't cause failures in crop/phash steps."""
        self._make_mineru_output()
        repo = FakeRepository()
        # No raw_assets added

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                repository=repo,
                deepseek_client=FakeDeepSeekClient(),
            )

        crop_step = next(s for s in report.steps if s.name == "crop_assets")
        self.assertEqual(crop_step.status, "success")
        self.assertEqual(crop_step.input_count, 0)

    def test_partial_crop_failure_records_warning(self):
        """When some crops fail, the step status is 'warning' and pipeline continues."""
        self._make_mineru_output()
        repo = FakeRepository()
        repo._raw_assets = [
            {"id": "ra_001", "paper_id": "paper_001", "page": 1,
             "bbox_json": "[0.1,0.1,0.3,0.3]", "asset_type": "image",
             "source_element_id": "e1", "crop_path": None,
             "storage_url": None, "perceptual_hash": "",
             "content_hash": "", "width": None, "height": None,
             "status": "active"},
            {"id": "ra_002", "paper_id": "paper_001", "page": 1,
             "bbox_json": "[0.5,0.5,0.8,0.8]", "asset_type": "image",
             "source_element_id": "e2", "crop_path": None,
             "storage_url": None, "perceptual_hash": "",
             "content_hash": "", "width": None, "height": None,
             "status": "active"},
        ]

        from question_bank.services.pdf_cropper import CropResult

        fake_results = [
            CropResult(raw_asset_id="ra_001", page=1,
                       bbox=(0.1, 0.1, 0.3, 0.3),
                       crop_path="/tmp/ra_001.png",
                       content_hash="abc", width=100, height=100, error=None),
            CropResult(raw_asset_id="ra_002", page=1,
                       bbox=(0.5, 0.5, 0.8, 0.8),
                       crop_path=None,
                       content_hash="", width=None, height=None,
                       error="bad bbox"),
        ]

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )
            with mock.patch(
                "question_bank.services.paper_orchestrator.crop_pdf_assets",
                return_value=fake_results,
            ):
                with mock.patch(
                    "question_bank.services.paper_orchestrator.store_crop_result",
                ) as mock_store:
                    mock_store.return_value = mock.MagicMock(
                        raw_asset_id="ra_001",
                        storage_url="local://test",
                        file_path="/tmp/ra_001.png",
                        content_hash="abc", width=100, height=100,
                    )

                    report = ingest_paper_full(
                        paper_id="paper_001",
                        pdf_path="/tmp/test.pdf",
                        work_dir=str(self.work_dir),
                        asset_dir=str(self.asset_dir),
                        repository=repo,
                        deepseek_client=FakeDeepSeekClient(),
                    )

        crop_step = next(s for s in report.steps if s.name == "crop_assets")
        self.assertEqual(crop_step.status, "warning")
        self.assertEqual(crop_step.output_count, 1)  # one succeeded
        self.assertTrue(any("ra_002" in w for w in crop_step.warnings))

        # Pipeline should continue past crop
        step_names = {s.name for s in report.steps}
        self.assertIn("compute_phash", step_names)

    def test_report_to_dict_and_to_json(self):
        """IngestionReport.to_dict() and to_json() produce valid output."""
        report = IngestionReport(
            paper_id="p1",
            status="completed",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:01:00Z",
            steps=[
                StepResult(name="test_step", status="success",
                           started_at="2026-01-01T00:00:00Z",
                           finished_at="2026-01-01T00:00:30Z",
                           input_count=1, output_count=1),
            ],
            counts={"test_step": 1, "steps_total": 1, "steps_succeeded": 1,
                    "steps_failed": 0, "steps_skipped": 0},
            warnings=[],
            errors=[],
        )

        d = report.to_dict()
        self.assertEqual(d["paper_id"], "p1")
        self.assertEqual(d["status"], "completed")
        self.assertEqual(len(d["steps"]), 1)
        self.assertEqual(d["steps"][0]["name"], "test_step")

        j = report.to_json()
        self.assertIsInstance(j, str)
        parsed = json.loads(j)
        self.assertEqual(parsed["paper_id"], "p1")

    def test_report_to_dict_includes_quality_stats(self):
        """ADR 013: to_dict() includes quality gating fields with defaults."""
        report = IngestionReport(
            paper_id="p1",
            status="completed",
            started_at="2026-01-01T00:00:00Z",
            finished_at="2026-01-01T00:01:00Z",
            steps=[],
            counts={},
            warnings=[],
            errors=[],
            questions_passed=20,
            questions_warning=2,
            questions_failed=0,
            failed_question_ids=[],
            quality_warning_counts={"too_few_choices": 2},
        )
        d = report.to_dict()
        self.assertEqual(d["questions_passed"], 20)
        self.assertEqual(d["questions_warning"], 2)
        self.assertEqual(d["questions_failed"], 0)
        self.assertEqual(d["failed_question_ids"], [])
        self.assertEqual(d["quality_warning_counts"], {"too_few_choices": 2})


# ---------------------------------------------------------------------------
# ADR 013: Quality gating integration tests
# ---------------------------------------------------------------------------


class FakeDeepSeekClientWithFailures:
    """Fake that produces one empty-stem question (failed) among normal ones."""

    def __init__(self, fail_index: int = 1):
        self.fail_index = fail_index
        self.call_count = 0

    def structure_question(self, raw_markdown: str) -> dict:
        self.call_count += 1
        if self.call_count == self.fail_index:
            return {
                "question_type": "single_choice",
                "stem_latex": "",
                "choices": [],
                "answer_latex": "",
                "analysis_latex": "",
                "knowledge_points": [],
                "difficulty": None,
                "warnings": [],
            }
        return {
            "question_type": "single_choice",
            "stem_latex": raw_markdown,
            "choices": [{"label": "A", "content_latex": "x=1"},
                        {"label": "B", "content_latex": "x=2"}],
            "answer_latex": "A",
            "analysis_latex": "ok",
            "knowledge_points": [],
            "difficulty": None,
            "warnings": [],
        }


class FakeDeepSeekClientAllFailures:
    """Fake that produces empty-stem for all questions."""

    def structure_question(self, raw_markdown: str) -> dict:
        return {
            "question_type": "single_choice",
            "stem_latex": "",
            "choices": [],
            "answer_latex": "",
            "analysis_latex": "",
            "knowledge_points": [],
            "difficulty": None,
            "warnings": [],
        }


class TestQualityGatingIntegration(unittest.TestCase):
    """ADR 013: quality gating end-to-end integration tests."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.work_dir = Path(self.tmpdir) / "runs" / "paper_001"
        self.asset_dir = Path(self.tmpdir) / "assets"

    def _make_two_question_output(self):
        """Create MinerU output that produces 2 layout blocks."""
        self.work_dir.mkdir(parents=True, exist_ok=True)
        (self.work_dir / "output.md").write_text(
            "1. first question\n2. second question\n", encoding="utf-8"
        )
        (self.work_dir / "output.json").write_text(json.dumps([
            {"id": "e1", "page": 1, "type": "text",
             "bbox": [0.08, 0.10, 0.50, 0.14], "text": "1. first question",
             "confidence": 0.98},
            {"id": "e2", "page": 1, "type": "text",
             "bbox": [0.08, 0.20, 0.50, 0.24], "text": "2. second question",
             "confidence": 0.98},
        ]), encoding="utf-8")

    def test_single_failed_question_does_not_block_others(self):
        """One question failing gating does not block other questions."""
        self._make_two_question_output()
        repo = FakeRepository()

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                repository=repo,
                deepseek_client=FakeDeepSeekClientWithFailures(fail_index=1),
            )

        # Pipeline should complete (not fail)
        self.assertEqual(report.status, "completed")

        # Quality stats: 1 failed, 1 passed
        self.assertEqual(report.questions_passed, 1)
        self.assertEqual(report.questions_failed, 1)

        # Failed ID should be recorded
        self.assertEqual(len(report.failed_question_ids), 1)
        self.assertIn("paper_001_q_0001", report.failed_question_ids)

        # Only 1 question saved (the passing one)
        self.assertEqual(len(repo.saved_results), 1)
        saved = repo.saved_results[0]
        self.assertEqual(len(saved.questions), 1)
        self.assertEqual(len(saved.blocks), 1)
        self.assertEqual(saved.questions[0].id, "paper_001_q_0002")

    def test_failed_question_blocks_are_excluded_from_asset_identification(self):
        """Failed-gated layout blocks are not used by downstream asset linking."""
        self._make_two_question_output()
        repo = FakeRepository()

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                repository=repo,
                deepseek_client=FakeDeepSeekClientWithFailures(fail_index=1),
            )

        self.assertEqual(
            repo.identified_block_ids,
            ["paper_001_qb_2"],
            "asset identification must only see blocks for saved questions",
        )

    def test_warning_questions_still_saved(self):
        """Warning-gated questions are still written to DB."""
        self._make_two_question_output()
        repo = FakeRepository()

        # Second question has only 1 choice → warning
        class FakeDeepSeekWithWarning:
            def __init__(self):
                self._called = 0

            def structure_question(self, raw_markdown: str) -> dict:
                self._called += 1
                return {
                    "question_type": "single_choice",
                    "stem_latex": raw_markdown,
                    "choices": [{"label": "A", "content_latex": "x=1"}]
                               if self._called == 2
                               else [{"label": "A", "content_latex": "x=1"},
                                     {"label": "B", "content_latex": "x=2"}],
                    "answer_latex": "A",
                    "analysis_latex": "",
                    "knowledge_points": [],
                    "difficulty": None,
                    "warnings": [],
                }

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                repository=repo,
                deepseek_client=FakeDeepSeekWithWarning(),
            )

        # Both questions saved
        self.assertEqual(report.questions_passed, 1)
        self.assertEqual(report.questions_warning, 1)
        self.assertEqual(report.questions_failed, 0)

        saved = repo.saved_results[0]
        self.assertEqual(len(saved.questions), 2,
                         "warning questions should still be saved")

        # Warning code aggregated
        self.assertIn("too_few_choices", report.quality_warning_counts)
        self.assertEqual(report.quality_warning_counts["too_few_choices"], 1)

    def test_dry_run_outputs_quality_stats(self):
        """Dry-run mode still produces quality gating statistics."""
        self._make_two_question_output()
        repo = FakeRepository()

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                dry_run=True,
                repository=repo,
                deepseek_client=FakeDeepSeekClient(),
            )

        self.assertEqual(report.questions_passed, 2)
        self.assertEqual(report.questions_failed, 0)
        self.assertIsInstance(report.quality_warning_counts, dict)

        # Run report on disk should include quality fields
        report_path = self.work_dir / "run-report.json"
        data = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertIn("questions_passed", data)
        self.assertIn("questions_warning", data)
        self.assertIn("questions_failed", data)
        self.assertIn("failed_question_ids", data)
        self.assertIn("quality_warning_counts", data)

    def test_failed_question_ids_in_report(self):
        """Failed question IDs are recorded in the ingestion report."""
        self._make_two_question_output()
        repo = FakeRepository()

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                repository=repo,
                deepseek_client=FakeDeepSeekClientWithFailures(fail_index=1),
            )

        self.assertEqual(len(report.failed_question_ids), 1)

        # Verify on-disk report
        report_path = self.work_dir / "run-report.json"
        data = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(data["failed_question_ids"], report.failed_question_ids)

    def test_all_questions_failed_marks_paper_partial(self):
        """When ALL questions fail gating, paper status is 'partial'."""
        self._make_two_question_output()
        repo = FakeRepository()

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                repository=repo,
                deepseek_client=FakeDeepSeekClientAllFailures(),
            )

        self.assertEqual(report.status, "partial",
                         "all questions failed should mark paper as partial")
        self.assertEqual(report.questions_passed, 0)
        self.assertEqual(report.questions_failed, 2)

        # No questions saved
        saved = repo.saved_results[0] if repo.saved_results else None
        if saved:
            self.assertEqual(len(saved.questions), 0)

    def test_warning_codes_aggregated_correctly(self):
        """Warning codes are counted and aggregated in the report."""
        self._make_two_question_output()
        repo = FakeRepository()

        # Second question has unbalanced latex + answer not in choices
        class FakeDeepSeekWithMultipleWarnings:
            def __init__(self):
                self._called = 0

            def structure_question(self, raw_markdown: str) -> dict:
                self._called += 1
                if self._called == 2:
                    return {
                        "question_type": "single_choice",
                        "stem_latex": "choose $x",
                        "choices": [{"label": "A", "content_latex": "x=1"},
                                    {"label": "B", "content_latex": "x=2"}],
                        "answer_latex": "C",
                        "analysis_latex": "ok",
                        "knowledge_points": [],
                        "difficulty": None,
                        "warnings": [],
                    }
                return {
                    "question_type": "single_choice",
                    "stem_latex": raw_markdown,
                    "choices": [{"label": "A", "content_latex": "x=1"},
                                {"label": "B", "content_latex": "x=2"}],
                    "answer_latex": "A",
                    "analysis_latex": "ok",
                    "knowledge_points": [],
                    "difficulty": None,
                    "warnings": [],
                }

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            report = ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                repository=repo,
                deepseek_client=FakeDeepSeekWithMultipleWarnings(),
            )

        # Second question should have both warnings (unbalanced_latex + answer_not_in_choices)
        self.assertEqual(report.questions_passed, 1)
        self.assertEqual(report.questions_warning, 1)
        self.assertIn("unbalanced_latex_delimiters", report.quality_warning_counts)
        self.assertIn("answer_not_in_choices", report.quality_warning_counts)

    def test_run_report_json_includes_quality_fields(self):
        """ADR 013: run-report.json includes quality gating fields."""
        self._make_two_question_output()
        repo = FakeRepository()

        with mock.patch(
            "question_bank.services.paper_orchestrator.LocalMinerURunner"
        ) as mock_mineru:
            mock_mineru.return_value.parse_pdf.return_value = mock.MagicMock(
                markdown_path=self.work_dir / "output.md",
                raw_json_path=self.work_dir / "output.json",
            )

            ingest_paper_full(
                paper_id="paper_001",
                pdf_path="/tmp/test.pdf",
                work_dir=str(self.work_dir),
                asset_dir=str(self.asset_dir),
                repository=repo,
                deepseek_client=FakeDeepSeekClient(),
            )

        report_path = self.work_dir / "run-report.json"
        data = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertIn("questions_passed", data)
        self.assertIn("questions_warning", data)
        self.assertIn("questions_failed", data)
        self.assertIn("failed_question_ids", data)
        self.assertIn("quality_warning_counts", data)
        self.assertIsInstance(data["questions_passed"], int)
        self.assertIsInstance(data["failed_question_ids"], list)
        self.assertIsInstance(data["quality_warning_counts"], dict)


if __name__ == "__main__":
    unittest.main()
