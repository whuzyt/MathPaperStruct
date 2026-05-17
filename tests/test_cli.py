import io
import json
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
        all_sql = fake_psycopg.connection.cursor_obj.all_sql
        self.assertIn("CREATE TABLE IF NOT EXISTS papers", all_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS duplicate_candidate_groups", all_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS canonical_questions", all_sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS raw_assets", all_sql)
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

    def test_review_asset_crop_parses_args_and_flows(self):
        import json as _json

        raw_rows = [
            {
                "id": "ra_001", "paper_id": "paper_01", "page": 1,
                "bbox_json": _json.dumps([0.1, 0.1, 0.5, 0.5]),
                "asset_type": "image", "source_element_id": "e_001",
                "crop_path": None, "storage_url": None,
                "perceptual_hash": "", "content_hash": "ch_old",
                "width": None, "height": None, "status": "active",
                "created_at": "2026-01-01",
            },
        ]
        fake_psycopg = FakePsycopgModule(rows=raw_rows)

        from question_bank.services.pdf_cropper import CropResult

        fake_crop_result = CropResult(
            raw_asset_id="ra_001", page=1,
            bbox=(0.1, 0.1, 0.5, 0.5),
            crop_path="/tmp/crop.png",
            content_hash="abc123",
            width=200, height=150, error=None,
        )

        from question_bank.services.local_asset_store import StoredAsset

        fake_stored = StoredAsset(
            raw_asset_id="ra_001",
            storage_url="local://assets/paper_01/ra_001.png",
            file_path="/tmp/assets/paper_01/ra_001.png",
            content_hash="abc123",
            width=200, height=150,
        )

        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            with patch(
                "question_bank.services.pdf_cropper.crop_pdf_assets",
                return_value=[fake_crop_result],
            ):
                with patch(
                    "question_bank.services.local_asset_store.store_crop_result",
                    return_value=fake_stored,
                ):
                    exit_code = main(
                        [
                            "review", "asset", "crop",
                            "--paper-id", "paper_01",
                            "--pdf", "/tmp/test.pdf",
                            "--output-dir", "/tmp/assets",
                        ],
                        stdout=stdout,
                        stderr=stderr,
                    )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Done: 1 succeeded, 0 failed", output)
        self.assertIn("Cropping 1 assets", output)

        # Verify UPDATE was executed
        cursor = fake_psycopg.connection.cursor_obj
        update_sqls = [s for s in cursor._all_sql if "UPDATE raw_assets" in s]
        self.assertEqual(len(update_sqls), 1)

    def test_review_asset_phash_parses_args_and_flows(self):
        import json as _json

        raw_rows = [
            {
                "id": "ra_001", "paper_id": "paper_01", "page": 1,
                "bbox_json": _json.dumps([0.1, 0.1, 0.5, 0.5]),
                "asset_type": "image", "source_element_id": "e_001",
                "crop_path": "/tmp/crop.png", "storage_url": "local://...",
                "perceptual_hash": "", "content_hash": "ch_abc",
                "width": 200, "height": 150, "status": "active",
                "created_at": "2026-01-01",
            },
        ]
        fake_psycopg = FakePsycopgModule(rows=raw_rows)

        stdout = io.StringIO()
        stderr = io.StringIO()

        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            with patch(
                "question_bank.services.image_phash.compute_phash",
                return_value="deadbeef00000000",
            ):
                exit_code = main(
                    ["review", "asset", "phash", "--paper-id", "paper_01"],
                    stdout=stdout,
                    stderr=stderr,
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Done: 1 hashed", output)
        self.assertIn("phash=deadbeef00000000", output)

    def test_review_asset_visual_candidates_parses_args_and_flows(self):
        import json as _json

        raw_rows = [
            {
                "id": "ra_001", "paper_id": "paper_01", "page": 1,
                "bbox_json": _json.dumps([0.1, 0.1, 0.5, 0.5]),
                "asset_type": "image", "source_element_id": "e_001",
                "crop_path": "/tmp/crop1.png", "storage_url": "local://...",
                "perceptual_hash": "000000000000000f", "content_hash": "ch_a",
                "width": 200, "height": 150, "status": "active",
                "created_at": "2026-01-01",
            },
            {
                "id": "ra_002", "paper_id": "paper_02", "page": 2,
                "bbox_json": _json.dumps([0.2, 0.2, 0.6, 0.6]),
                "asset_type": "image", "source_element_id": "e_002",
                "crop_path": "/tmp/crop2.png", "storage_url": "local://...",
                "perceptual_hash": "000000000000000e", "content_hash": "ch_b",
                "width": 180, "height": 140, "status": "active",
                "created_at": "2026-01-01",
            },
        ]
        fake_psycopg = FakePsycopgModule(rows=raw_rows)

        stdout = io.StringIO()
        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            exit_code = main(
                ["review", "asset", "visual-candidates", "--max-distance", "8"],
                stdout=stdout,
            )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("visual candidate group", output.lower())


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
        self._all_sql: list[str] = []
        self.sql = ""
        self.params = None
        self.rows = rows or []

    def execute(self, sql, params=None):
        self._all_sql.append(sql)
        self.sql = sql
        self.params = params

    @property
    def all_sql(self) -> str:
        return "\n".join(self._all_sql)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


    def test_env_enable_layout_ownership_runs_shadow_without_cli_flag(self):
        """ENABLE_LAYOUT_OWNERSHIP=true enables shadow even without --enable-layout-ownership."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            markdown_path = tmp / "paper.md"
            markdown_path.write_text("1. 已知 $x=1$。\n2. 如图，求面积。", encoding="utf-8")
            elements_path = tmp / "elements.json"
            elements_path.write_text(
                json.dumps([
                    {"id": "e1", "page": 1, "type": "text",
                     "bbox": [0.08, 0.10, 0.50, 0.14], "text": "1. 已知 $x=1$。"},
                    {"id": "e2", "page": 1, "type": "text",
                     "bbox": [0.08, 0.20, 0.50, 0.24], "text": "2. 如图，求面积。"},
                ]),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch.dict("os.environ", {"ENABLE_LAYOUT_OWNERSHIP": "true"}):
                exit_code = main(
                    [
                        "ingest",
                        "--paper-id", "paper_001",
                        "--from-markdown", str(markdown_path),
                        "--layout-elements", str(elements_path),
                        "--dry-run",
                    ],
                    stdout=stdout,
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Layout Ownership Shadow Comparison", output)
        self.assertIn("paper_001", output)
        self.assertIn("old splitter question_count", output)

    def test_from_markdown_shadow_uses_original_markdown_as_baseline(self):
        """Shadow old-splitter baseline comes from the raw file, not pipeline blocks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Original markdown has a section header, answer section, and 3 questions
            original_content = (
                "一、选择题\n"
                "1. 选题一\n"
                "A. 选项A\n"
                "2. 选题二\n"
                "B. 选项B\n"
                "参考答案\n"
                "1. A\n"
                "2. B\n"
            )
            markdown_path = tmp / "paper.md"
            markdown_path.write_text(original_content, encoding="utf-8")
            elements_path = tmp / "elements.json"
            elements_path.write_text(
                json.dumps([
                    {"id": "s1", "page": 1, "type": "text",
                     "bbox": [0.08, 0.06, 0.50, 0.09], "text": "一、选择题"},
                    {"id": "e1", "page": 1, "type": "text",
                     "bbox": [0.08, 0.12, 0.50, 0.16], "text": "1. 选题一"},
                    {"id": "e1a", "page": 1, "type": "text",
                     "bbox": [0.08, 0.18, 0.50, 0.22], "text": "A. 选项A"},
                    {"id": "e2", "page": 1, "type": "text",
                     "bbox": [0.08, 0.25, 0.50, 0.29], "text": "2. 选题二"},
                    {"id": "e2b", "page": 1, "type": "text",
                     "bbox": [0.08, 0.31, 0.50, 0.35], "text": "B. 选项B"},
                    {"id": "ans_hdr", "page": 1, "type": "text",
                     "bbox": [0.08, 0.70, 0.50, 0.74], "text": "参考答案"},
                    {"id": "ans1", "page": 1, "type": "text",
                     "bbox": [0.08, 0.76, 0.50, 0.80], "text": "1. A"},
                    {"id": "ans2", "page": 1, "type": "text",
                     "bbox": [0.08, 0.82, 0.50, 0.86], "text": "2. B"},
                ]),
                encoding="utf-8",
            )
            stdout = io.StringIO()

            with patch.dict("os.environ", {"ENABLE_LAYOUT_OWNERSHIP": "true"}):
                exit_code = main(
                    [
                        "ingest",
                        "--paper-id", "paper_001",
                        "--from-markdown", str(markdown_path),
                        "--layout-elements", str(elements_path),
                        "--enable-layout-ownership",
                        "--dry-run",
                    ],
                    stdout=stdout,
                )

        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        # The old splitter, when run on the original markdown, splits
        # document sections first — body only has 2 questions (1, 2)
        # before the answer section. So old_question_count should be 2.
        self.assertIn("Layout Ownership Shadow Comparison", output)
        self.assertIn("old splitter question_count : 2", output)
        # Pipeline result (printed in summary) should also have 2 questions
        self.assertIn("questions=2", output)


if __name__ == "__main__":
    unittest.main()
