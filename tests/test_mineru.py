import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from question_bank.services.mineru import LocalMinerURunner, MinerUResult


class LocalMinerURunnerTest(unittest.TestCase):
    def test_builds_command_with_formula_and_ocr_flags(self):
        runner = LocalMinerURunner(command="magic-pdf", enable_formula=True, enable_ocr=True)

        command = runner.build_command(Path("/tmp/paper.pdf"), Path("/tmp/out"))

        self.assertEqual(
            command,
            [
                "magic-pdf",
                "-p",
                "/tmp/paper.pdf",
                "-o",
                "/tmp/out",
                "-f",
                "true",
                "-m",
                "auto",
            ],
        )

    def test_builds_command_without_optional_flags(self):
        runner = LocalMinerURunner(command="magic-pdf", enable_formula=False, enable_ocr=False)

        command = runner.build_command(Path("/tmp/paper.pdf"), Path("/tmp/out"))

        self.assertEqual(
            command,
            ["magic-pdf", "-p", "/tmp/paper.pdf", "-o", "/tmp/out", "-f", "false", "-m", "txt"],
        )

    def test_parse_pdf_discovers_mineru_3x_nested_output(self):
        """MinerU 3.x nests output: output_dir/<pdf_name>/auto/<pdf_name>.md etc."""
        runner = LocalMinerURunner(command="mineru")

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "out"
            pdf_path = Path(tmpdir) / "test_paper.pdf"
            pdf_path.write_text("fake pdf content")

            # Simulate MinerU 3.1.14 output structure (pipeline backend, auto method)
            parse_dir = out_dir / "test_paper" / "auto"
            parse_dir.mkdir(parents=True)
            (parse_dir / "test_paper.md").write_text("# Test Markdown")
            (parse_dir / "test_paper_content_list.json").write_text(
                json.dumps([{"type": "text", "text": "hello", "bbox": [0, 0, 1, 1], "page_idx": 0}])
            )
            (parse_dir / "test_paper_middle.json").write_text(
                json.dumps([{"id": "e1", "type": "text", "text": "hello"}])
            )
            (parse_dir / "images").mkdir()

            # Mock subprocess.run to skip actual MinerU execution
            with mock.patch("subprocess.run"):
                result = runner.parse_pdf(pdf_path, out_dir)

            self.assertEqual(result.markdown_path, parse_dir / "test_paper.md")
            self.assertEqual(result.raw_json_path, parse_dir / "test_paper_content_list.json")
            self.assertEqual(result.assets_dir, parse_dir / "images")

    def test_parse_pdf_falls_back_to_middle_json_when_no_content_list(self):
        """_middle.json remains a compatibility fallback when content_list is absent."""
        runner = LocalMinerURunner(command="mineru")

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "out"
            pdf_path = Path(tmpdir) / "test_paper.pdf"
            pdf_path.write_text("fake pdf content")

            parse_dir = out_dir / "test_paper" / "auto"
            parse_dir.mkdir(parents=True)
            (parse_dir / "test_paper.md").write_text("# Test Markdown")
            (parse_dir / "test_paper_middle.json").write_text(
                json.dumps([{"id": "e1", "type": "text", "text": "hello"}])
            )

            with mock.patch("subprocess.run"):
                result = runner.parse_pdf(pdf_path, out_dir)

            self.assertEqual(result.raw_json_path, parse_dir / "test_paper_middle.json")

    def test_parse_pdf_falls_back_to_any_json_when_no_middle_json(self):
        """Old MinerU or non-pipeline backends may not produce _middle.json."""
        runner = LocalMinerURunner(command="mineru")

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "out"
            pdf_path = Path(tmpdir) / "paper.pdf"
            pdf_path.write_text("fake")

            # Hybrid backend output: <pdf_name>/hybrid_auto/
            parse_dir = out_dir / "paper" / "hybrid_auto"
            parse_dir.mkdir(parents=True)
            (parse_dir / "paper.md").write_text("# MD")
            # No _middle.json — only a plain output.json
            (parse_dir / "output.json").write_text(
                json.dumps([{"id": "e1", "type": "text"}])
            )

            with mock.patch("subprocess.run"):
                result = runner.parse_pdf(pdf_path, out_dir)

            self.assertEqual(result.markdown_path, parse_dir / "paper.md")
            self.assertEqual(result.raw_json_path, parse_dir / "output.json")
            self.assertIsNone(result.assets_dir)

    def test_parse_pdf_returns_none_paths_when_no_artifacts(self):
        """When MinerU produces no recognizable output, paths are None."""
        runner = LocalMinerURunner(command="mineru")

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "out"
            pdf_path = Path(tmpdir) / "empty.pdf"
            pdf_path.write_text("empty")

            # Create out_dir but no artifacts inside
            out_dir.mkdir(parents=True)

            with mock.patch("subprocess.run"):
                result = runner.parse_pdf(pdf_path, out_dir)

            self.assertIsNone(result.markdown_path)
            self.assertIsNone(result.raw_json_path)
            self.assertIsNone(result.assets_dir)

    def test_parse_pdf_raises_on_subprocess_error(self):
        """If MinerU exits non-zero, the error includes exit code and stderr."""
        import subprocess as sp

        runner = LocalMinerURunner(command="mineru")

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "out"
            pdf_path = Path(tmpdir) / "bad.pdf"
            pdf_path.write_text("bad")

            error = sp.CalledProcessError(1, ["mineru"], stderr="model download failed\nfatal error")
            with mock.patch("subprocess.run", side_effect=error):
                with self.assertRaisesRegex(RuntimeError, "MinerU exited with code 1"):
                    runner.parse_pdf(pdf_path, out_dir)


if __name__ == "__main__":
    unittest.main()
