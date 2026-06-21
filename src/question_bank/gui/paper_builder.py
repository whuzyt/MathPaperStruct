from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from question_bank.services.paper_builder import (
    PaperBuildPaths,
    export_paper_markdown,
    load_exported_questions,
    question_display_text,
)


class PaperBuilderWindow(tk.Toplevel):
    def __init__(self, parent: tk.Tk, *, default_output_dir: Path) -> None:
        super().__init__(parent)
        self.title("MathPaperStruct 组卷")
        self.geometry("920x640")
        self.minsize(760, 500)
        self.transient(parent)

        self.output_dir = tk.StringVar(value=str(default_output_dir))
        self.paper_title = tk.StringVar(value="数学试卷")
        self.status = tk.StringVar(value="导入一个或多个题目 JSON 后，选择要组卷的题目。")
        self.questions: list[dict] = []
        self.last_paths: PaperBuildPaths | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        controls = ttk.LabelFrame(self, text="试卷设置", padding=12)
        controls.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="试卷标题").grid(row=0, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(controls, textvariable=self.paper_title).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Label(controls, text="输出目录").grid(row=1, column=0, sticky="w", padx=(0, 10), pady=4)
        ttk.Entry(controls, textvariable=self.output_dir).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(controls, text="选择", command=self._choose_output_dir).grid(row=1, column=2, padx=(8, 0), pady=4)

        content = ttk.Frame(self, padding=(16, 0, 16, 8))
        content.grid(row=1, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)
        actions = ttk.Frame(content)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(actions, text="导入题目 JSON", command=self._import_json).pack(side="left")
        ttk.Button(actions, text="全选", command=self._select_all).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="清空选择", command=self._clear_selection).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="上移", command=lambda: self._move_selected(-1)).pack(side="left", padx=(16, 0))
        ttk.Button(actions, text="下移", command=lambda: self._move_selected(1)).pack(side="left", padx=(8, 0))

        list_frame = ttk.Frame(content)
        list_frame.grid(row=1, column=0, sticky="nsew")
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        self.question_list = tk.Listbox(list_frame, selectmode="extended", activestyle="none")
        self.question_list.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.question_list.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.question_list.configure(yscrollcommand=scroll.set)

        footer = ttk.Frame(self, padding=(16, 0, 16, 16))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status, foreground="#475569").grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="导出试卷", command=self._export).grid(row=0, column=1, padx=(12, 0))
        self.open_button = ttk.Button(footer, text="打开试卷", command=self._open_paper, state="disabled")
        self.open_button.grid(row=0, column=2, padx=(8, 0))

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="选择组卷输出目录")
        if path:
            self.output_dir.set(path)

    def _import_json(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择解析后的题目 JSON",
            filetypes=[("题目 JSON", "*_questions.json"), ("JSON 文件", "*.json")],
        )
        if not paths:
            return
        try:
            imported = load_exported_questions([Path(path) for path in paths])
        except ValueError as exc:
            messagebox.showerror("导入失败", str(exc))
            return
        self.questions.extend(imported)
        self._refresh_list(select_new=True, start_index=len(self.questions) - len(imported))
        self.status.set(f"已导入 {len(imported)} 题；当前共 {len(self.questions)} 题。")

    def _refresh_list(self, *, select_new: bool = False, start_index: int = 0) -> None:
        selected = set(self.question_list.curselection())
        self.question_list.delete(0, tk.END)
        for index, question in enumerate(self.questions):
            self.question_list.insert(tk.END, question_display_text(question, index))
            if index in selected or (select_new and index >= start_index):
                self.question_list.selection_set(index)

    def _select_all(self) -> None:
        self.question_list.selection_set(0, tk.END)

    def _clear_selection(self) -> None:
        self.question_list.selection_clear(0, tk.END)

    def _move_selected(self, offset: int) -> None:
        selected = list(self.question_list.curselection())
        if len(selected) != 1:
            messagebox.showinfo("调整顺序", "请选择一题后再上移或下移。")
            return
        index = selected[0]
        target = index + offset
        if target < 0 or target >= len(self.questions):
            return
        self.questions[index], self.questions[target] = self.questions[target], self.questions[index]
        self._refresh_list()
        self.question_list.selection_set(target)

    def _export(self) -> None:
        selected = list(self.question_list.curselection())
        if not selected:
            messagebox.showerror("无法导出", "请至少选择一道题。")
            return
        try:
            paths = export_paper_markdown(
                title=self.paper_title.get(),
                questions=[self.questions[index] for index in selected],
                output_dir=Path(self.output_dir.get()).expanduser(),
            )
        except ValueError as exc:
            messagebox.showerror("无法导出", str(exc))
            return
        self.last_paths = paths
        self.open_button.configure(state="normal")
        self.status.set(f"已导出 {len(selected)} 题：{paths.paper_path.name}")
        messagebox.showinfo(
            "组卷完成",
            f"试卷：\n{paths.paper_path}\n\n答案与解析：\n{paths.answer_path}",
        )

    def _open_paper(self) -> None:
        if not self.last_paths:
            return
        target = self.last_paths.paper_path
        if sys.platform == "darwin":
            subprocess.run(["open", str(target)], check=False)
        elif os.name == "nt":
            os.startfile(str(target))  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", str(target)], check=False)
