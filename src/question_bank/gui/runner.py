from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from question_bank.config import Settings
from question_bank.pipeline import ProcessingResult
from question_bank.services.deepseek import DeepSeekHTTPClient, FakeDeepSeekClient
from question_bank.services.paper_orchestrator import (
    GatingResult,
    IngestionReport,
    StepResult,
    _finalize,
    _now_iso,
    _step_deepseek_structure,
    _step_layout_ownership,
    _step_mineru_parse,
)

from .export import ExportPaths, export_questions


ProgressCallback = Callable[[str], None]


@dataclass(slots=True)
class GuiIngestOptions:
    paper_id: str
    pdf_path: Path
    output_dir: Path
    mineru_command: str
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    use_real_deepseek: bool = True
    resume: bool = True


@dataclass(slots=True)
class GuiIngestResult:
    report: IngestionReport
    processing_result: ProcessingResult | None
    export_paths: ExportPaths | None
    log_lines: list[str] = field(default_factory=list)


def default_options(pdf_path: Path, *, output_root: Path | None = None) -> GuiIngestOptions:
    settings = Settings.load()
    stem = pdf_path.stem.strip() or "paper"
    safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)
    paper_id = safe_stem[:80] or "paper"
    root = output_root or Path("data") / "gui_runs"
    return GuiIngestOptions(
        paper_id=paper_id,
        pdf_path=pdf_path,
        output_dir=root / paper_id,
        mineru_command=settings.mineru_command,
        deepseek_api_key=settings.deepseek_api_key or "",
        deepseek_base_url=settings.deepseek_base_url,
        deepseek_model=settings.deepseek_model,
        use_real_deepseek=bool(settings.deepseek_api_key),
    )


def run_gui_ingest(
    options: GuiIngestOptions,
    progress: ProgressCallback | None = None,
) -> GuiIngestResult:
    log_lines: list[str] = []

    def emit(message: str) -> None:
        log_lines.append(message)
        if progress:
            progress(message)

    output_dir = options.output_dir
    work_dir = output_dir / "work"
    export_dir = output_dir / "exports"
    work_dir.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)

    ctx: dict = {}
    steps: list[StepResult] = []
    started_at = _now_iso()

    deepseek_client = _build_deepseek_client(options)

    pipeline = [
        ("MinerU 解析 PDF", _step_mineru_parse, (
            options.paper_id,
            str(options.pdf_path),
            str(work_dir),
            options.resume,
            options.mineru_command,
            ctx,
        )),
        ("版面归属与切题", _step_layout_ownership, (options.paper_id, ctx)),
        ("DeepSeek 结构化题目", _step_deepseek_structure, (options.paper_id, deepseek_client, ctx)),
    ]

    for index, (label, step_fn, args) in enumerate(pipeline, start=1):
        emit(f"[{index}/3] {label}...")
        try:
            with _capture_stdout(emit):
                step = step_fn(*args)
        except Exception as exc:
            step = StepResult(
                name=step_fn.__name__.replace("_step_", ""),
                status="failed",
                started_at=_now_iso(),
                finished_at=_now_iso(),
                error=str(exc),
            )
            steps.append(step)
            emit(f"失败：{exc}")
            report = _finalize(options.paper_id, started_at, steps, work_dir, ctx)
            return GuiIngestResult(
                report=report,
                processing_result=ctx.get("processing_result"),
                export_paths=None,
                log_lines=log_lines,
            )
        steps.append(step)
        emit(f"完成：{step.status}，输出 {step.output_count}")
        if step.status == "failed":
            report = _finalize(options.paper_id, started_at, steps, work_dir, ctx)
            return GuiIngestResult(
                report=report,
                processing_result=ctx.get("processing_result"),
                export_paths=None,
                log_lines=log_lines,
            )

    processing_result: ProcessingResult | None = ctx.get("processing_result")
    export_paths = export_questions(processing_result, export_dir) if processing_result else None

    if export_paths:
        emit(f"已导出 JSON：{export_paths.json_path}")
        emit(f"已导出 Markdown：{export_paths.markdown_path}")

    report = _finalize(options.paper_id, started_at, steps, work_dir, ctx)
    return GuiIngestResult(
        report=report,
        processing_result=processing_result,
        export_paths=export_paths,
        log_lines=log_lines,
    )


def _build_deepseek_client(options: GuiIngestOptions):
    if not options.use_real_deepseek:
        return FakeDeepSeekClient()
    api_key = options.deepseek_api_key.strip()
    if not api_key:
        raise ValueError("请填写 DeepSeek API Key，或关闭真实 DeepSeek。")
    return DeepSeekHTTPClient(
        api_key=api_key,
        base_url=options.deepseek_base_url,
        model=options.deepseek_model,
    )


@contextlib.contextmanager
def _capture_stdout(emit: ProgressCallback):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        yield
    text = buffer.getvalue().strip()
    if text:
        for line in text.splitlines():
            emit(line)

