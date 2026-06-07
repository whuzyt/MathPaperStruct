from __future__ import annotations

import contextlib
import io
import queue
import shutil
import subprocess
import threading
import time
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
    _discover_mineru_json_files,
    _finalize,
    _now_iso,
    _step_deepseek_structure,
    _step_layout_ownership,
    _validate_resume_artifacts,
)
from question_bank.services.mineru import MinerUResult, _discover_artifacts

from .export import ExportPaths, export_questions


ProgressCallback = Callable[[str], None]
PROJECT_ROOT = Path(__file__).resolve().parents[3]


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
        mineru_command=detect_mineru_command(configured=settings.mineru_command),
        deepseek_api_key=settings.deepseek_api_key or "",
        deepseek_base_url=settings.deepseek_base_url,
        deepseek_model=settings.deepseek_model,
        use_real_deepseek=bool(settings.deepseek_api_key),
    )


def detect_mineru_command(
    *,
    project_root: Path = PROJECT_ROOT,
    configured: str = "mineru",
) -> str:
    configured = configured.strip() or "mineru"
    configured_path = Path(configured).expanduser()
    if (configured_path.is_absolute() or "/" in configured) and configured_path.exists():
        return str(configured_path)

    project_venv_mineru = project_root / ".venv" / "bin" / "mineru"
    if project_venv_mineru.exists():
        return str(project_venv_mineru)

    found = shutil.which(configured)
    if found:
        return found

    found_mineru = shutil.which("mineru")
    if found_mineru:
        return found_mineru

    return configured


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
        ("MinerU 解析 PDF", _step_mineru_parse_gui, (options, work_dir, ctx, emit)),
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


def build_mineru_command(
    *,
    mineru_command: str,
    pdf_path: Path,
    output_dir: Path,
) -> list[str]:
    return [
        mineru_command,
        "-p",
        str(pdf_path),
        "-o",
        str(output_dir),
        "-f",
        "true",
        "-m",
        "auto",
    ]


def _step_mineru_parse_gui(
    options: GuiIngestOptions,
    work_dir: Path,
    ctx: dict,
    emit: ProgressCallback,
) -> StepResult:
    started = _now_iso()

    if options.resume:
        md_files = list(work_dir.rglob("*.md"))
        json_files = _discover_mineru_json_files(work_dir)
        if md_files and json_files and _validate_resume_artifacts(md_files[0], json_files[0]):
            ctx["mineru_result"] = MinerUResult(
                output_dir=work_dir,
                markdown_path=md_files[0],
                raw_json_path=json_files[0],
            )
            emit("发现可复用 MinerU 输出，跳过 PDF 解析。")
            return StepResult(
                name="mineru_parse",
                status="skipped",
                started_at=started,
                finished_at=_now_iso(),
            )

    work_dir.mkdir(parents=True, exist_ok=True)
    cmd = build_mineru_command(
        mineru_command=options.mineru_command,
        pdf_path=options.pdf_path,
        output_dir=work_dir,
    )
    emit("$ " + " ".join(cmd))
    emit("MinerU 首次运行可能会初始化模型/API，耗时较长。")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    line_queue: queue.Queue[str] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            line_queue.put(line.rstrip())

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()

    last_heartbeat = time.monotonic()
    while process.poll() is None:
        _drain_mineru_lines(line_queue, emit)
        now = time.monotonic()
        if now - last_heartbeat >= 15:
            elapsed = int(now - last_heartbeat)
            emit(f"MinerU 仍在运行，最近 {elapsed} 秒无新日志。")
            last_heartbeat = now
        time.sleep(0.5)

    _drain_mineru_lines(line_queue, emit)
    reader.join(timeout=1)
    _drain_mineru_lines(line_queue, emit)
    if process.returncode != 0:
        raise RuntimeError(f"MinerU exited with code {process.returncode}")

    result = _discover_artifacts(work_dir, options.pdf_path.stem)
    ctx["mineru_result"] = result
    ok = 1 if result.markdown_path and result.markdown_path.exists() else 0
    return StepResult(
        name="mineru_parse",
        status="success",
        started_at=started,
        finished_at=_now_iso(),
        input_count=1,
        output_count=ok,
    )


def _drain_mineru_lines(line_queue: queue.Queue[str], emit: ProgressCallback) -> None:
    while True:
        try:
            line = line_queue.get_nowait()
        except queue.Empty:
            return
        if line.strip():
            emit(line)


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
