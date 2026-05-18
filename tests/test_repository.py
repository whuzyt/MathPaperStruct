import unittest

from question_bank.domain.models import Choice, Question, QuestionAsset, QuestionBlock, QualityIssue, QualityReport
from question_bank.pipeline import ProcessingResult
from question_bank.repository import PostgresQuestionBankRepository


class RepositoryTest(unittest.TestCase):
    def test_saves_processing_result_to_core_tables(self):
        connection = FakeConnection()
        repository = PostgresQuestionBankRepository(connection)
        result = ProcessingResult(
            paper_id="paper_001",
            blocks=[
                QuestionBlock(
                    id="qb_001",
                    paper_id="paper_001",
                    question_number="1",
                    section_title="一、选择题",
                    raw_markdown="1. 题干",
                )
            ],
            questions=[
                Question(
                    id="q_001",
                    question_type="single_choice",
                    stem_latex="题干",
                    choices=[Choice(label="A", content_latex="$1$", sort_order=1)],
                    answer_latex="A",
                    analysis_latex="解析",
                    knowledge_points=["一次函数"],
                    assets=[QuestionAsset(id="asset_001", type="image", storage_url="s3://bucket/a.png")],
                )
            ],
            quality_reports=[
                QualityReport(
                    question_id="q_001",
                    issues=[QualityIssue(code="missing_stem", message="题干为空。")],
                    model_warnings=["answer_missing"],
                    overall_score=0.8,
                    needs_review=True,
                )
            ],
        )

        repository.save_processing_result(result)

        tables = [statement.table for statement in connection.cursor_obj.statements]
        self.assertEqual(
            tables,
            [
                "papers",
                "question_blocks",
                "questions",
                "choices",
                "question_assets",
                "quality_reports",
            ],
        )
        self.assertTrue(connection.committed)
        quality_params = connection.cursor_obj.statements[-1].params
        self.assertEqual(quality_params["id"], "q_001_quality")
        self.assertIn("missing_stem", quality_params["rule_errors"])
        self.assertIn("answer_missing", quality_params["model_warnings"])

    def test_rolls_back_when_insert_fails(self):
        connection = FakeConnection(fail_on_table="questions")
        repository = PostgresQuestionBankRepository(connection)
        result = ProcessingResult(
            paper_id="paper_001",
            blocks=[
                QuestionBlock(
                    id="qb_001",
                    paper_id="paper_001",
                    question_number="1",
                    raw_markdown="1. 题干",
                )
            ],
            questions=[Question(id="q_001", question_type="short_answer", stem_latex="题干")],
            quality_reports=[QualityReport(question_id="q_001")],
        )

        with self.assertRaises(RuntimeError):
            repository.save_processing_result(result)

        self.assertTrue(connection.rolled_back)
        self.assertFalse(connection.committed)

    def test_lists_review_queue_items(self):
        rows = [
            {
                "question_id": "q_001",
                "question_type": "single_choice",
                "stem_latex": "题干一",
                "overall_score": 0.6,
                "rule_errors": '[{"code":"too_few_choices"}]',
                "model_warnings": '["fake_client_output"]',
            }
        ]
        connection = FakeConnection(rows=rows)
        repository = PostgresQuestionBankRepository(connection)

        items = repository.list_review_queue(limit=10)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].question_id, "q_001")
        self.assertEqual(items[0].error_codes, ["too_few_choices"])
        self.assertEqual(items[0].model_warnings, ["fake_client_output"])
        self.assertIn("WHERE qr.needs_review = true", connection.cursor_obj.statements[-1].sql)


class ExecutedStatement:
    def __init__(self, sql, params):
        self.sql = sql
        self.params = params
        self.table = sql.split("INSERT INTO ", 1)[1].split(" ", 1)[0] if "INSERT INTO " in sql else ""


class FakeCursor:
    def __init__(self, fail_on_table=None, rows=None):
        self.fail_on_table = fail_on_table
        self.rows = rows or []
        self.statements = []

    def execute(self, sql, params=None):
        statement = ExecutedStatement(sql, params)
        if statement.table == self.fail_on_table:
            raise RuntimeError("insert failed")
        self.statements.append(statement)

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, fail_on_table=None, rows=None):
        self.cursor_obj = FakeCursor(fail_on_table=fail_on_table, rows=rows)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


if __name__ == "__main__":
    unittest.main()
