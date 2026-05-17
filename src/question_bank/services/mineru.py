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
        cmd.extend(["-f", "true" if self.enable_formula else "false"])
        cmd.extend(["-m", "auto" if self.enable_ocr else "txt"])
        return cmd

    def parse_pdf(self, pdf_path: Path, output_dir: Path) -> MinerUResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(self.build_command(pdf_path, output_dir), check=True)

        pdf_stem = pdf_path.stem

        # MinerU 3.x nests output: output_dir/<pdf_name>/<method>/<pdf_name>.md
        # The method directory varies by backend (auto, txt, ocr, hybrid_auto, etc.)
        # Discover artifacts by globbing rather than hardcoding paths.
        md_candidates = sorted(output_dir.rglob(f"{pdf_stem}.md"))
        json_candidates = sorted(output_dir.rglob(f"{pdf_stem}_middle.json"))
        # Fall back: old MinerU versions or alternative filenames
        if not json_candidates:
            json_candidates = sorted(output_dir.rglob("*.json"))
        img_candidates = sorted(
            d for d in output_dir.rglob("images") if d.is_dir()
        )

        return MinerUResult(
            output_dir=output_dir,
            markdown_path=md_candidates[0] if md_candidates else None,
            raw_json_path=json_candidates[0] if json_candidates else None,
            assets_dir=img_candidates[0] if img_candidates else None,
        )
