from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None  # type: ignore[assignment]

from question_bank.api.app import create_app


@unittest.skipIf(TestClient is None, "FastAPI test client is not installed")
class ApiConsoleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.runs = self.root / "data" / "runs"
        self.evals = self.root / "docs" / "eval"
        self.runs.mkdir(parents=True)
        self.evals.mkdir(parents=True)

        run_dir = self.runs / "paper_001"
        run_dir.mkdir()
        (run_dir / "run-report.json").write_text(
            json.dumps({
                "paper_id": "paper_001",
                "status": "completed",
                "questions_passed": 12,
                "questions_warning": 1,
                "questions_failed": 0,
                "quality_warning_counts": {"too_few_choices": 1},
            }),
            encoding="utf-8",
        )
        (self.evals / "production-pilot.md").write_text(
            "# Production Pilot\n\nPASS\n",
            encoding="utf-8",
        )

        patcher = patch("question_bank.api.app.PROJECT_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        self.client = TestClient(create_app())

    def test_health_alias(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_home_page_renders_console(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("MathPaperStruct Console", response.text)
        self.assertIn("paper_001", response.text)
        self.assertIn("production-pilot.md", response.text)

    def test_ingest_page_renders_form(self):
        response = self.client.get("/ingest")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Start Ingest", response.text)
        self.assertIn("name=\"paper_id\"", response.text)
        self.assertIn("name=\"pdf_path\"", response.text)

    def test_runs_api_lists_recent_run_reports(self):
        response = self.client.get("/api/runs")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["runs"][0]["paper_id"], "paper_001")
        self.assertEqual(data["runs"][0]["questions_warning"], 1)
        self.assertEqual(data["runs"][0]["quality_warning_counts"], {"too_few_choices": 1})

    def test_evals_api_lists_markdown_reports(self):
        response = self.client.get("/api/evals")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["evals"][0]["name"], "production-pilot.md")
        self.assertIn("Production Pilot", data["evals"][0]["title"])


if __name__ == "__main__":
    unittest.main()
