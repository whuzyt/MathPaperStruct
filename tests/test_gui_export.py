from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from question_bank.domain.models import Choice, QualityReport, Question, QuestionAsset, QuestionBlock
from question_bank.gui.export import export_questions, processing_result_to_dicts
from question_bank.gui.runner import build_mineru_command, detect_mineru_command
from question_bank.pipeline import ProcessingResult


def _sample_result() -> ProcessingResult:
    return ProcessingResult(
        paper_id="paper_gui",
        blocks=[
            QuestionBlock(
                id="qb1",
                paper_id="paper_gui",
                question_number="1",
                raw_markdown="1. 已知 $x=1$，求 $x+1$。",
                pages=[1],
                assets=[
                    QuestionAsset(
                        id="img1",
                        type="image",
                        storage_url="local://assets/img1.png",
                        page=1,
                        bbox=(0.1, 0.2, 0.3, 0.4),
                        caption="示意图",
                    )
                ],
            )
        ],
        questions=[
            Question(
                id="paper_gui_q_0001",
                question_type="single_choice",
                stem_latex="已知 $x=1$，求 $x+1$。",
                choices=[
                    Choice(label="A", content_latex="$1$", sort_order=1),
                    Choice(label="B", content_latex="$2$", sort_order=2),
                ],
                answer_latex="B",
                analysis_latex="$x+1=2$。",
                knowledge_points=["代数"],
                difficulty=1,
            )
        ],
        quality_reports=[
            QualityReport(question_id="paper_gui_q_0001", model_warnings=[]),
        ],
    )


class GuiExportTest(unittest.TestCase):
    def test_processing_result_to_dicts_contains_user_visible_fields(self):
        rows = processing_result_to_dicts(_sample_result())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["question_number"], "1")
        self.assertEqual(rows[0]["question_type"], "single_choice")
        self.assertEqual(rows[0]["stem_latex"], "已知 $x=1$，求 $x+1$。")
        self.assertEqual(rows[0]["choices"][1]["label"], "B")
        self.assertEqual(rows[0]["answer_latex"], "B")
        self.assertEqual(rows[0]["assets"][0]["id"], "img1")
        self.assertEqual(rows[0]["assets"][0]["bbox"], [0.1, 0.2, 0.3, 0.4])
        self.assertEqual(rows[0]["quality"]["needs_review"], False)

    def test_export_questions_writes_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = export_questions(_sample_result(), Path(tmp))

            self.assertTrue(paths.json_path.exists())
            self.assertTrue(paths.markdown_path.exists())

            data = json.loads(paths.json_path.read_text(encoding="utf-8"))
            self.assertEqual(data["paper_id"], "paper_gui")
            self.assertEqual(data["question_count"], 1)
            self.assertEqual(data["questions"][0]["answer_latex"], "B")

            markdown = paths.markdown_path.read_text(encoding="utf-8")
            self.assertIn("# paper_gui 题目导出", markdown)
            self.assertIn("## 第 1 题", markdown)
            self.assertIn("- B. $2$", markdown)
            self.assertIn("**答案**：B", markdown)


class GuiRunnerConfigTest(unittest.TestCase):
    def test_detect_mineru_command_prefers_project_venv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mineru = root / ".venv" / "bin" / "mineru"
            mineru.parent.mkdir(parents=True)
            mineru.write_text("#!/bin/sh\n", encoding="utf-8")
            mineru.chmod(0o755)

            self.assertEqual(
                detect_mineru_command(project_root=root, configured="mineru"),
                str(mineru),
            )

    def test_detect_mineru_command_keeps_existing_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            command = Path(tmp) / "mineru"
            command.write_text("#!/bin/sh\n", encoding="utf-8")
            command.chmod(0o755)

            self.assertEqual(detect_mineru_command(configured=str(command)), str(command))

    def test_build_mineru_command_uses_pdf_and_output_paths(self):
        command = build_mineru_command(
            mineru_command="/tmp/mineru",
            pdf_path=Path("/tmp/input.pdf"),
            output_dir=Path("/tmp/out"),
        )

        self.assertEqual(command, [
            "/tmp/mineru",
            "-p",
            "/tmp/input.pdf",
            "-o",
            "/tmp/out",
            "-f",
            "true",
            "-m",
            "auto",
        ])


if __name__ == "__main__":
    unittest.main()
