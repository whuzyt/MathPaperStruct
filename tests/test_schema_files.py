from pathlib import Path
import unittest


class SchemaFilesTest(unittest.TestCase):
    def test_initial_schema_contains_core_prd_tables(self):
        schema = Path("db/001_initial_schema.sql").read_text(encoding="utf-8")

        for table in [
            "papers",
            "parse_runs",
            "question_blocks",
            "questions",
            "choices",
            "question_assets",
            "quality_reports",
        ]:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", schema)

        self.assertIn("CREATE INDEX IF NOT EXISTS idx_questions_review_status", schema)
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_question_blocks_paper_id", schema)


if __name__ == "__main__":
    unittest.main()

