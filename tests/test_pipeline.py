import unittest

from question_bank.pipeline import ProcessingPipeline
from question_bank.services.deepseek import FakeDeepSeekClient


class ProcessingPipelineTest(unittest.TestCase):
    def test_processes_markdown_into_question_records_with_quality_reports(self):
        markdown = """
一、解答题
1. 已知 $x=1$，求 $x+1$。
2. 如图，求阴影部分面积。
"""
        pipeline = ProcessingPipeline(deepseek_client=FakeDeepSeekClient())

        result = pipeline.process_markdown("paper_001", markdown)

        self.assertEqual(result.paper_id, "paper_001")
        self.assertEqual(len(result.blocks), 2)
        self.assertEqual(len(result.questions), 2)
        self.assertEqual(result.questions[0].id, "paper_001_q_0001")
        self.assertEqual(result.quality_reports[1].question_id, "paper_001_q_0002")
        self.assertTrue(result.quality_reports[1].needs_review)
        self.assertEqual(result.quality_reports[0].model_warnings, ["fake_client_output"])

    def test_process_and_save_uses_repository(self):
        pipeline = ProcessingPipeline(deepseek_client=FakeDeepSeekClient())
        repository = RecordingRepository()

        result = pipeline.process_and_save_markdown("paper_001", "1. 已知 $x=1$。", repository)

        self.assertIs(repository.saved_result, result)
        self.assertEqual(len(result.questions), 1)

    def test_merges_answer_section_into_questions(self):
        markdown = """
一、选择题
1. 已知 $x=1$，求 $x+1$。
2. 已知 $y=2$，求 $y+1$。
参考答案
1. $2$
2. $3$
"""
        pipeline = ProcessingPipeline(deepseek_client=FakeDeepSeekClient())

        result = pipeline.process_markdown("paper_001", markdown)

        self.assertEqual(result.questions[0].answer_latex, "$2$")
        self.assertEqual(result.questions[1].answer_latex, "$3$")
        self.assertNotIn("missing_answer", [issue.code for issue in result.quality_reports[0].issues])

    def test_merges_answer_and_analysis_section_into_questions(self):
        markdown = """
三、解答
1. 解方程 $x+1=2$。
参考答案
1. 答案：$x=1$ 解析：移项得 $x=1$。
"""
        pipeline = ProcessingPipeline(deepseek_client=FakeDeepSeekClient())

        result = pipeline.process_markdown("paper_001", markdown)

        self.assertEqual(result.questions[0].answer_latex, "$x=1$")
        self.assertEqual(result.questions[0].analysis_latex, "移项得 $x=1$。")

    def test_falls_back_to_parsed_choices_when_model_returns_no_choices(self):
        markdown = """
一、选择题
1. 下列计算正确的是（ ）
A. $1+1=3$
B. $2+2=4$
参考答案
1. B
"""
        pipeline = ProcessingPipeline(deepseek_client=FakeDeepSeekClient())

        result = pipeline.process_markdown("paper_001", markdown)

        self.assertEqual([choice.label for choice in result.questions[0].choices], ["A", "B"])
        self.assertEqual(result.questions[0].choices[1].content_latex, "$2+2=4$")
        self.assertEqual(str(result.questions[0].question_type), "single_choice")

    def test_infers_fill_blank_type_before_quality_validation(self):
        markdown = """
二、填空题
1. 计算 $2^3=$____。
参考答案
1. $8$
"""
        pipeline = ProcessingPipeline(deepseek_client=FakeDeepSeekClient())

        result = pipeline.process_markdown("paper_001", markdown)

        self.assertEqual(str(result.questions[0].question_type), "fill_blank")
        self.assertNotIn("missing_answer", [issue.code for issue in result.quality_reports[0].issues])


class RecordingRepository:
    def __init__(self):
        self.saved_result = None

    def save_processing_result(self, result):
        self.saved_result = result


if __name__ == "__main__":
    unittest.main()
