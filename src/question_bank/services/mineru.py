from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


# ---------------------------------------------------------------------------
# ADR 021: transient error patterns for MinerU retry
# ---------------------------------------------------------------------------


_TRANSIENT_ERROR_PATTERNS: tuple[str, ...] = (
    "All connection attempts failed",
    "Timed out while polling task status",
    "Connection reset",
    "Connection refused",
    "Connection aborted",
    "Remote end closed connection",
    "Could not resolve host",
    "Temporary failure in name resolution",
    "connect timed out",
    "Read timed out",
    "broken pipe",
    "Network is unreachable",
)

_NON_TRANSIENT_ERROR_PATTERNS: tuple[str, ...] = (
    "No such file or directory",
    "PDF file not found",
    "FileNotFoundError",
    "model",
    "Model",
    "invalid argument",
    "unknown option",
    "Cannot open",
    "Permission denied",
)


def _is_transient_error(error_message: str) -> bool:
    """ADR 021: classify whether a MinerU failure is transient and retryable."""
    msg_lower = error_message
    # Non-transient checks first (safety: don't retry the wrong thing)
    for pattern in _NON_TRANSIENT_ERROR_PATTERNS:
        if pattern.lower() in msg_lower.lower():
            return False
    for pattern in _TRANSIENT_ERROR_PATTERNS:
        if pattern.lower() in msg_lower.lower():
            return True
    return False


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


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
    # ADR 021: automatic retry for transient failures
    max_retries: int = 2
    retry_backoff_base: float = 30.0  # seconds

    def build_command(self, pdf_path: Path, output_dir: Path) -> list[str]:
        cmd = [self.command, "-p", str(pdf_path), "-o", str(output_dir)]
        cmd.extend(["-f", "true" if self.enable_formula else "false"])
        cmd.extend(["-m", "auto" if self.enable_ocr else "txt"])
        return cmd

    def parse_pdf(self, pdf_path: Path, output_dir: Path) -> MinerUResult:
        """ADR 021: run MinerU with automatic retry for transient failures."""
        output_dir.mkdir(parents=True, exist_ok=True)
        cmd = self.build_command(pdf_path, output_dir)
        print(f"    $ {' '.join(cmd)}")
        print("    (first run may download models, ~2-5 GB)")

        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                delay = self.retry_backoff_base * (2 ** (attempt - 1))
                print(f"    Retry {attempt}/{self.max_retries} after {delay:.0f}s...")
                time.sleep(delay)

            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as exc:
                # Check both str(exc) and exc.output for transient patterns.
                # CalledProcessError stores the actual error output in .output;
                # str(exc) only contains the generic command + returncode message.
                error_msg = getattr(exc, "output", "") or ""
                error_msg = f"{str(exc)}\n{error_msg}"
                if _is_transient_error(error_msg):
                    last_error = exc
                    continue
                raise RuntimeError(
                    f"MinerU exited with code {exc.returncode}"
                ) from exc

            # Success — break out of retry loop
            last_error = None
            break

        if last_error is not None:
            raise RuntimeError(
                f"MinerU failed after {self.max_retries + 1} attempts: {last_error}"
            ) from last_error

        return _discover_artifacts(output_dir, pdf_path.stem)


def _discover_artifacts(output_dir: Path, pdf_stem: str) -> MinerUResult:
    """ADR 021: discover MinerU output artifacts by globbing."""
    md_candidates = sorted(output_dir.rglob(f"{pdf_stem}.md"))
    # Prefer content_list: it is the flat element stream closest to our
    # layout ownership contract. _middle.json is a nested MinerU internals
    # dict in 3.x and is kept only as a compatibility fallback.
    json_candidates = sorted(output_dir.rglob(f"{pdf_stem}_content_list.json"))
    if not json_candidates:
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
