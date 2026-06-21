from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from question_bank.services.paper_builder import (
    export_paper_markdown,
    load_exported_questions,
    question_display_text,
)


def _question(number: str, *, question_type: str = "single_choice") -> dict:
    return {
        "question_number": number,
        "question_type": question_type,
        "stem_latex": f"第 {number} 题：已知 $x=1$，求 $x+1$。",
        "choices": [
            {"label": "A", "content_latex": "$1$"},
            {"label": "B", "content_latex": "$2$"},
        ] if question_type == "single_choice" else [],
        "answer_latex": "B" if question_type == "single_choice" else "$2$",
        "analysis_latex": "代入可得 $x+1=2$。",
    }


class PaperBuilderTest(unittest.TestCase):
    def test_load_exported_questions_collects_multiple_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first_questions.json"
            second = root / "second_questions.json"
            first.write_text(json.dumps({"questions": [_question("1")]}, ensure_ascii=False), encoding="utf-8")
            second.write_text(json.dumps({"questions": [_question("2")]}, ensure_ascii=False), encoding="utf-8")

            loaded = load_exported_questions([first, second])

            self.assertEqual([q["question_number"] for q in loaded], ["1", "2"])
            self.assertEqual(loaded[0]["_source"], str(first))

    def test_load_exported_questions_rejects_invalid_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{}", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_exported_questions([path])

    def test_export_writes_question_paper_and_answer_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = export_paper_markdown(
                title="平面向量练习",
                questions=[_question("例1-1"), _question("例2", question_type="fill_blank")],
                output_dir=Path(tmp),
            )

            paper = paths.paper_path.read_text(encoding="utf-8")
            answers = paths.answer_path.read_text(encoding="utf-8")

            self.assertIn("# 平面向量练习", paper)
            self.assertIn("## 1.", paper)
            self.assertIn("A. $1$", paper)
            self.assertIn("答：", paper)
            self.assertNotIn("**答案**", paper)
            self.assertIn("# 平面向量练习 答案与解析", answers)
            self.assertIn("**答案**：B", answers)
            self.assertIn("代入可得", answers)

    def test_export_rejects_blank_title_or_empty_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                export_paper_markdown(title="", questions=[_question("1")], output_dir=Path(tmp))
            with self.assertRaises(ValueError):
                export_paper_markdown(title="测试", questions=[], output_dir=Path(tmp))

    def test_question_display_text_is_compact(self):
        question = _question("例1-1")

        text = question_display_text(question, 0)

        self.assertIn("1. [例1-1] single_choice", text)
        self.assertIn("已知", text)


if __name__ == "__main__":
    unittest.main()
