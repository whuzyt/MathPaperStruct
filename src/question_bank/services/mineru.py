from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class MinerUResult:
    output_dir: Path
    markdown_path: Path | None = None
    raw_json_path: Path | None = None
    assets_dir: Path | None = None


class MinerURunnerProtocol(Protocol):
    def parse_pdf(self, pdf_path: Path, output_dir: Path) -> MinerUResult:
        """Parse a PDF into MinerU artifacts."""


@dataclass(slots=True)
class LocalMinerURunner:
    command: str = "mineru"
    enable_formula: bool = True
    enable_ocr: bool = True

    def build_command(self, pdf_path: Path, output_dir: Path) -> list[str]:
        cmd = [self.command, "-p", str(pdf_path), "-o", str(output_dir)]
        if self.enable_formula:
            cmd.append("--enable-formula")
        if self.enable_ocr:
            cmd.append("--enable-ocr")
        return cmd

    def parse_pdf(self, pdf_path: Path, output_dir: Path) -> MinerUResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(self.build_command(pdf_path, output_dir), check=True)
        return MinerUResult(
            output_dir=output_dir,
            markdown_path=output_dir / "output.md",
            raw_json_path=output_dir / "output.json",
            assets_dir=output_dir / "images",
        )

