from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PaperBuildPaths:
    paper_path: Path
    answer_path: Path


def load_exported_questions(paths: list[Path]) -> list[dict[str, Any]]:
    """Load user-facing question exports produced by the desktop parser."""
    questions: list[dict[str, Any]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"无法读取题目文件：{path}") from exc
        rows = payload.get("questions") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError(f"题目文件格式不正确：{path}")
        for row in rows:
            if not isinstance(row, dict) or not str(row.get("stem_latex", "")).strip():
                continue
            question = dict(row)
            question["_source"] = str(path)
            questions.append(question)
    return questions


def export_paper_markdown(
    *,
    title: str,
    questions: list[dict[str, Any]],
    output_dir: Path,
) -> PaperBuildPaths:
    if not title.strip():
        raise ValueError("请填写试卷标题。")
    if not questions:
        raise ValueError("请至少选择一道题。")

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_title = _safe_filename(title)
    paper_path = output_dir / f"{safe_title}_试卷.md"
    answer_path = output_dir / f"{safe_title}_答案与解析.md"
    paper_path.write_text(_paper_markdown(title, questions), encoding="utf-8")
    answer_path.write_text(_answer_markdown(title, questions), encoding="utf-8")
    return PaperBuildPaths(paper_path=paper_path, answer_path=answer_path)


def question_display_text(question: dict[str, Any], index: int) -> str:
    source_number = str(question.get("question_number") or "-")
    q_type = str(question.get("question_type") or "unknown")
    stem = re.sub(r"\s+", " ", str(question.get("stem_latex") or "")).strip()
    preview = stem[:70] + ("..." if len(stem) > 70 else "")
    return f"{index + 1}. [{source_number}] {q_type}  {preview}"


def _paper_markdown(title: str, questions: list[dict[str, Any]]) -> str:
    lines = [f"# {title}", "", f"共 {len(questions)} 题", ""]
    for index, question in enumerate(questions, start=1):
        lines.extend([f"## {index}.", "", str(question.get("stem_latex", "")).strip(), ""])
        for choice in question.get("choices") or []:
            label = str(choice.get("label", "")).strip()
            content = str(choice.get("content_latex", "")).strip()
            if label or content:
                lines.append(f"{label}. {content}".strip())
        if question.get("choices"):
            lines.append("")
        if str(question.get("question_type", "")) in {"short_answer", "proof", "fill_blank"}:
            lines.extend(["答：", "", ""])
    return "\n".join(lines).rstrip() + "\n"


def _answer_markdown(title: str, questions: list[dict[str, Any]]) -> str:
    lines = [f"# {title} 答案与解析", ""]
    for index, question in enumerate(questions, start=1):
        answer = str(question.get("answer_latex", "")).strip() or "（原题未提供答案）"
        analysis = str(question.get("analysis_latex", "")).strip()
        lines.extend([f"## {index}.", "", f"**答案**：{answer}", ""])
        if analysis:
            lines.extend(["**解析**", "", analysis, ""])
    return "\n".join(lines).rstrip() + "\n"


def _safe_filename(title: str) -> str:
    safe = re.sub(r"[\\/:*?\"<>|]+", "_", title.strip())
    return safe[:80] or "试卷"
