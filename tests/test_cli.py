import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from question_bank.cli import main


class CLITest(unittest.TestCase):
    def test_dry_run_from_markdown_prints_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            markdown_path = Path(tmpdir) / "paper.md"
            markdown_path.write_text("1. 已知 $x=1$。\n2. 如图，求面积。", encoding="utf-8")
            stdout = io.StringIO()

            exit_code = main(
                [
                    "ingest",
                    "--paper-id",
                    "paper_001",
                    "--from-markdown",
                    str(markdown_path),
                    "--dry-run",
                ],
                stdout=stdout,
            )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("paper_id=paper_001", output)
        self.assertIn("blocks=2", output)
        self.assertIn("questions=2", output)
        self.assertIn("needs_review=2", output)

    def test_pdf_mode_requires_deepseek_key_when_not_fake(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4")
            stderr = io.StringIO()

            exit_code = main(
                [
                    "ingest",
                    "--paper-id",
                    "paper_001",
                    "--pdf",
                    str(pdf_path),
                    "--output-dir",
                    str(Path(tmpdir) / "out"),
                    "--use-real-deepseek",
                ],
                stderr=stderr,
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("DEEPSEEK_API_KEY is required", stderr.getvalue())

    def test_db_mode_requires_psycopg_dependency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            markdown_path = Path(tmpdir) / "paper.md"
            markdown_path.write_text("1. 题干", encoding="utf-8")
            stderr = io.StringIO()

            with patch.dict("sys.modules", {"psycopg": None}):
                exit_code = main(
                    [
                        "ingest",
                        "--paper-id",
                        "paper_001",
                        "--from-markdown",
                        str(markdown_path),
                        "--save-db",
                    ],
                    stderr=stderr,
                )

        self.assertEqual(exit_code, 2)
        self.assertIn("psycopg is required", stderr.getvalue())

    def test_db_init_executes_schema_file(self):
        stdout = io.StringIO()
        fake_psycopg = FakePsycopgModule()

        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            exit_code = main(["db", "init"], stdout=stdout)

        self.assertEqual(exit_code, 0)
        self.assertIn("schema initialized", stdout.getvalue())
        self.assertIn("CREATE TABLE IF NOT EXISTS papers", fake_psycopg.connection.cursor_obj.sql)
        self.assertTrue(fake_psycopg.connection.committed)

    def test_review_list_prints_review_queue_items(self):
        stdout = io.StringIO()
        rows = [
            {
                "question_id": "q_001",
                "question_type": "single_choice",
                "stem_latex": "题干一很长很长很长很长很长很长",
                "overall_score": 0.6,
                "rule_errors": '[{"code":"too_few_choices"}]',
                "model_warnings": '["fake_client_output"]',
            }
        ]
        fake_psycopg = FakePsycopgModule(rows=rows)

        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            exit_code = main(["review", "list", "--limit", "5"], stdout=stdout)

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("q_001", output)
        self.assertIn("too_few_choices", output)
        self.assertIn("fake_client_output", output)


class FakePsycopgModule:
    def __init__(self, rows=None):
        self.connection = FakeConnection(rows=rows)
        self.last_database_url = ""

    def connect(self, database_url):
        self.last_database_url = database_url
        return self.connection


class FakeConnection:
    def __init__(self, rows=None):
        self.cursor_obj = FakeCursor(rows=rows)
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("rollback should not be called")


class FakeCursor:
    def __init__(self, rows=None):
        self.sql = ""
        self.params = None
        self.rows = rows or []

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


if __name__ == "__main__":
    unittest.main()
