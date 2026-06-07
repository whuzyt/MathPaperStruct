from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .runner import GuiIngestOptions, default_options, run_gui_ingest


class MathPaperStructApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MathPaperStruct 题库解析器")
        self.geometry("980x720")
        self.minsize(860, 620)

        self.pdf_path = tk.StringVar()
        self.paper_id = tk.StringVar()
        self.output_dir = tk.StringVar(value=str(Path("data/gui_runs").resolve()))
        self.mineru_command = tk.StringVar(value=".venv/bin/mineru")
        self.deepseek_api_key = tk.StringVar(value=os.environ.get("DEEPSEEK_API_KEY", ""))
        self.deepseek_base_url = tk.StringVar(value=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
        self.deepseek_model = tk.StringVar(value=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"))
        self.use_real_deepseek = tk.BooleanVar(value=bool(self.deepseek_api_key.get()))
        self.resume = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="请选择一个 PDF 开始。")

        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._running = False
        self._last_output_dir: Path | None = None

        self._build_ui()
        self.after(120, self._poll_events)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(18, 16, 18, 10))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header,
            text="MathPaperStruct 题库解析器",
            font=("", 22, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="选择数学试卷 PDF，一键解析为结构化题目并导出 JSON / Markdown。",
            foreground="#5b6472",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        body = ttk.Frame(self, padding=(18, 0, 18, 14))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(2, weight=1)

        input_frame = ttk.LabelFrame(body, text="输入", padding=12)
        input_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        input_frame.columnconfigure(1, weight=1)

        self._row_file(input_frame, 0, "PDF 文件", self.pdf_path, self._choose_pdf)
        self._row_text(input_frame, 1, "Paper ID", self.paper_id)
        self._row_file(input_frame, 2, "输出目录", self.output_dir, self._choose_output_dir)

        config_frame = ttk.LabelFrame(body, text="解析配置", padding=12)
        config_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 0), padx=(0, 8))
        config_frame.columnconfigure(1, weight=1)
        self._row_text(config_frame, 0, "MinerU 命令", self.mineru_command)
        self._row_text(config_frame, 1, "DeepSeek Key", self.deepseek_api_key, show="*")
        self._row_text(config_frame, 2, "模型", self.deepseek_model)
        ttk.Checkbutton(
            config_frame,
            text="使用真实 DeepSeek",
            variable=self.use_real_deepseek,
        ).grid(row=3, column=1, sticky="w", pady=(8, 0))
        ttk.Checkbutton(
            config_frame,
            text="复用已有 MinerU 输出",
            variable=self.resume,
        ).grid(row=4, column=1, sticky="w", pady=(4, 0))

        action_frame = ttk.LabelFrame(body, text="操作", padding=12)
        action_frame.grid(row=1, column=1, sticky="nsew", pady=(12, 0), padx=(8, 0))
        action_frame.columnconfigure(0, weight=1)
        self.start_button = ttk.Button(
            action_frame,
            text="开始解析 PDF",
            command=self._start,
        )
        self.start_button.grid(row=0, column=0, sticky="ew")
        ttk.Button(
            action_frame,
            text="打开输出目录",
            command=self._open_output_dir,
        ).grid(row=1, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(
            action_frame,
            text="清空日志",
            command=self._clear_log,
        ).grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(
            action_frame,
            textvariable=self.status,
            wraplength=360,
            foreground="#475569",
        ).grid(row=3, column=0, sticky="ew", pady=(16, 0))

        log_frame = ttk.LabelFrame(body, text="进度日志", padding=8)
        log_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(log_frame, wrap="word", height=18, state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

    def _row_text(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        *,
        show: str | None = None,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 10))
        ttk.Entry(parent, textvariable=variable, show=show).grid(row=row, column=1, sticky="ew", pady=5)

    def _row_file(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        command,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 10))
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Button(parent, text="选择", command=command).grid(row=row, column=2, sticky="e", padx=(8, 0))

    def _choose_pdf(self) -> None:
        path = filedialog.askopenfilename(
            title="选择数学试卷 PDF",
            filetypes=[("PDF 文件", "*.pdf"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.pdf_path.set(path)
        options = default_options(Path(path), output_root=Path(self.output_dir.get()))
        self.paper_id.set(options.paper_id)
        if not self.deepseek_api_key.get().strip():
            self.deepseek_api_key.set(options.deepseek_api_key)
        if self.mineru_command.get() == ".venv/bin/mineru":
            self.mineru_command.set(options.mineru_command)

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir.set(path)

    def _start(self) -> None:
        if self._running:
            return
        try:
            options = self._collect_options()
        except ValueError as exc:
            messagebox.showerror("无法开始", str(exc))
            return

        self._running = True
        self.start_button.configure(state="disabled")
        self.status.set("正在解析，请不要关闭窗口。")
        self._append_log("开始解析。")
        worker = threading.Thread(target=self._run_worker, args=(options,), daemon=True)
        worker.start()

    def _collect_options(self) -> GuiIngestOptions:
        pdf = Path(self.pdf_path.get()).expanduser()
        if not pdf.exists():
            raise ValueError("请选择存在的 PDF 文件。")
        paper_id = self.paper_id.get().strip()
        if not paper_id:
            raise ValueError("请填写 Paper ID。")
        output_root = Path(self.output_dir.get()).expanduser()
        output_dir = output_root / paper_id
        mineru_command = self.mineru_command.get().strip()
        if not mineru_command:
            raise ValueError("请填写 MinerU 命令。")
        return GuiIngestOptions(
            paper_id=paper_id,
            pdf_path=pdf,
            output_dir=output_dir,
            mineru_command=mineru_command,
            deepseek_api_key=self.deepseek_api_key.get().strip(),
            deepseek_base_url=self.deepseek_base_url.get().strip(),
            deepseek_model=self.deepseek_model.get().strip() or "deepseek-chat",
            use_real_deepseek=self.use_real_deepseek.get(),
            resume=self.resume.get(),
        )

    def _run_worker(self, options: GuiIngestOptions) -> None:
        try:
            result = run_gui_ingest(options, progress=lambda msg: self._events.put(("log", msg)))
        except Exception as exc:
            self._events.put(("error", str(exc)))
            return
        self._events.put(("done", result))

    def _poll_events(self) -> None:
        while True:
            try:
                kind, payload = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._append_log(str(payload))
            elif kind == "error":
                self._running = False
                self.start_button.configure(state="normal")
                self.status.set("解析失败。")
                self._append_log(f"失败：{payload}")
                messagebox.showerror("解析失败", str(payload))
            elif kind == "done":
                self._handle_done(payload)
        self.after(120, self._poll_events)

    def _handle_done(self, result) -> None:
        self._running = False
        self.start_button.configure(state="normal")
        self._last_output_dir = Path(self.output_dir.get()) / result.report.paper_id
        total = (
            result.report.questions_passed
            + result.report.questions_warning
            + result.report.questions_failed
        )
        self.status.set(
            f"完成：{total} 题，pass {result.report.questions_passed}，"
            f"warning {result.report.questions_warning}，failed {result.report.questions_failed}。"
        )
        self._append_log(self.status.get())
        if result.export_paths:
            self._append_log(f"JSON：{result.export_paths.json_path}")
            self._append_log(f"Markdown：{result.export_paths.markdown_path}")
        if result.report.errors:
            messagebox.showwarning("解析完成但有错误", "\n".join(result.report.errors))
        else:
            messagebox.showinfo("解析完成", self.status.get())

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _open_output_dir(self) -> None:
        target = self._last_output_dir or Path(self.output_dir.get()).expanduser()
        target.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            subprocess.run(["open", str(target)], check=False)
        elif os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(target)], check=False)


def main() -> None:
    app = MathPaperStructApp()
    app.mainloop()


if __name__ == "__main__":
    main()

