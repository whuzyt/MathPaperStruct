from __future__ import annotations

from dataclasses import dataclass
import re

from question_bank.domain.models import Choice, QuestionBlock


SECTION_PATTERN = re.compile(
    r"^[一二三四五六七八九十]+[、.．]\s*(选择|填空|解答|计算|证明|应用|综合|压轴).*$"
)
ANSWER_SECTION_PATTERN = re.compile(r"^(参考答案|答案|解析|答案与解析|试卷答案|详解)\s*$")
QUESTION_PATTERN = re.compile(r"^\s*(?:第\s*)?(\d{1,3})(?:\s*题)?(?:[、.．]\s*(.*)|\s*)$")
CHOICE_PATTERN = re.compile(r"^\s*([A-H])\s*[.．、:：]\s*(.*)$")


@dataclass(frozen=True, slots=True)
class DocumentSections:
    body_markdown: str
    answer_markdown: str


@dataclass(frozen=True, slots=True)
class ParsedAnswerEntry:
    raw_text: str
    answer_latex: str = ""
    analysis_latex: str = ""


def split_markdown_into_blocks(paper_id: str, markdown: str) -> list[QuestionBlock]:
    """Split MinerU-style Markdown into coarse question blocks.

    This is intentionally deterministic. DeepSeek can refine ambiguous blocks later,
    but the first split should be cheap, explainable, and easy to review.
    """

    sections = split_document_sections(markdown)
    markdown = sections.body_markdown
    blocks: list[QuestionBlock] = []
    current_lines: list[str] = []
    current_number = ""
    current_section = ""

    def flush() -> None:
        nonlocal current_lines, current_number
        if not current_lines or not current_number:
            current_lines = []
            return
        block_index = len(blocks) + 1
        raw_markdown = "\n".join(current_lines).strip()
        blocks.append(
            QuestionBlock(
                id=f"{paper_id}_qb_{block_index:04d}",
                paper_id=paper_id,
                question_number=current_number,
                section_title=current_section,
                raw_markdown=raw_markdown,
            )
        )
        current_lines = []

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if SECTION_PATTERN.match(line):
            flush()
            current_section = line
            continue

        match = QUESTION_PATTERN.match(line)
        if match:
            flush()
            current_number = match.group(1)
            remainder = (match.group(2) or "").strip()
            current_lines = [line if remainder else line]
            continue

        if current_lines:
            current_lines.append(line)

    flush()
    return blocks


def split_document_sections(markdown: str) -> DocumentSections:
    body_lines: list[str] = []
    answer_lines: list[str] = []
    in_answer_section = False

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if ANSWER_SECTION_PATTERN.match(line):
            in_answer_section = True
            continue

        if in_answer_section:
            answer_lines.append(line)
        else:
            body_lines.append(line)

    return DocumentSections(
        body_markdown="\n".join(body_lines).strip(),
        answer_markdown="\n".join(answer_lines).strip(),
    )


def parse_answer_entries(answer_markdown: str) -> dict[str, str]:
    entries: dict[str, list[str]] = {}
    current_number = ""

    for raw_line in answer_markdown.splitlines():
        line = raw_line.strip()
        if not line or ANSWER_SECTION_PATTERN.match(line):
            continue

        match = QUESTION_PATTERN.match(line)
        if match:
            current_number = match.group(1)
            remainder = (match.group(2) or "").strip()
            entries[current_number] = [remainder] if remainder else []
            continue

        if current_number:
            entries[current_number].append(line)

    return {
        number: "\n".join(lines).strip()
        for number, lines in entries.items()
        if "\n".join(lines).strip()
    }


def parse_answer_entry(raw_text: str) -> ParsedAnswerEntry:
    text = raw_text.strip()
    if not text:
        return ParsedAnswerEntry(raw_text="")

    answer_analysis_match = re.match(
        r"^(?:答案|答)[:：]\s*(.*?)\s*(?:解析|详解|解法)[:：]\s*(.*)$",
        text,
        flags=re.S,
    )
    if answer_analysis_match:
        return ParsedAnswerEntry(
            raw_text=text,
            answer_latex=answer_analysis_match.group(1).strip(),
            analysis_latex=answer_analysis_match.group(2).strip(),
        )

    analysis_answer_match = re.match(
        r"^(?:解析|详解|解法|解)[:：]\s*(.*?)\s*(?:答案|答)[:：]\s*(.*)$",
        text,
        flags=re.S,
    )
    if analysis_answer_match:
        return ParsedAnswerEntry(
            raw_text=text,
            answer_latex=analysis_answer_match.group(2).strip(),
            analysis_latex=analysis_answer_match.group(1).strip(),
        )

    answer_only_match = re.match(r"^(?:答案|答)[:：]\s*(.*)$", text, flags=re.S)
    if answer_only_match:
        return ParsedAnswerEntry(raw_text=text, answer_latex=answer_only_match.group(1).strip())

    analysis_only_match = re.match(r"^(?:解析|详解|解法|解)[:：]\s*(.*)$", text, flags=re.S)
    if analysis_only_match:
        return ParsedAnswerEntry(raw_text=text, analysis_latex=analysis_only_match.group(1).strip())

    return ParsedAnswerEntry(raw_text=text, answer_latex=text)


def parse_choices(raw_block: str) -> list[Choice]:
    choices: list[Choice] = []
    current_label = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_label, current_lines
        if not current_label:
            return
        content = "\n".join(current_lines).strip()
        if content:
            choices.append(
                Choice(
                    label=current_label,
                    content_latex=content,
                    sort_order=len(choices) + 1,
                )
            )
        current_label = ""
        current_lines = []

    for raw_line in raw_block.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = CHOICE_PATTERN.match(line)
        if match:
            flush()
            current_label = match.group(1)
            current_lines = [match.group(2).strip()] if match.group(2).strip() else []
            continue

        if current_label:
            current_lines.append(line)

    flush()
    return choices
