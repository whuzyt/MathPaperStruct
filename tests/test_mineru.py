import unittest
from pathlib import Path

from question_bank.services.mineru import LocalMinerURunner


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
                "--enable-formula",
                "--enable-ocr",
            ],
        )

    def test_builds_command_without_optional_flags(self):
        runner = LocalMinerURunner(command="magic-pdf", enable_formula=False, enable_ocr=False)

        command = runner.build_command(Path("/tmp/paper.pdf"), Path("/tmp/out"))

        self.assertEqual(command, ["magic-pdf", "-p", "/tmp/paper.pdf", "-o", "/tmp/out"])


if __name__ == "__main__":
    unittest.main()

