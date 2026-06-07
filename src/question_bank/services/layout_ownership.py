from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Patterns (ADR 001)
# ---------------------------------------------------------------------------
SECTION_PATTERN = re.compile(
    r"^[一二三四五六七八九十]+[、.．]\s*(选择|非选择|填空|解答|计算|证明|应用|综合|压轴).*$"
)
# Non-standard section markers: "向量小题A", "考点一", "专题二", "第3章" etc.
ALT_SECTION_PATTERN = re.compile(
    r"^(?:向量\s*)?小题[A-Z]$|"
    r"^(?:考点|专题|模块)[一二三四五六七八九十0-9]+|"
    r"^第[0-9一二三四五六七八九十]+[章节]"
)
# Nonstandard subsection markers: trigger section_hierarchy_suspected when
# a question number repeats >= 3 times across changing section titles that
# match this pattern.
NONSTANDARD_SUBSECTION_PATTERN = re.compile(
    r"(?:小题|专题|模块|题组|类型|考点|向量小题|"
    r"第[一二三四五六七八九十]+组|"
    r"[A-H][组类])"
)
ANSWER_SECTION_PATTERN = re.compile(
    r"^(参考答案|答案|解析|答案与解析|试卷答案|详解)\s*$"
)
QUESTION_ARABIC_PATTERN = re.compile(
    r"^\s*(?:第\s*)?([0-9]{1,3})(?:\s*题)?\s*[\.．、)：：]\s*"
)
QUESTION_CHINESE_PATTERN = re.compile(
    r"^\s*[（(]?\s*([一二三四五六七八九十]{1,4})\s*[）)、.．：：]\s*"
)
LECTURE_QUESTION_PATTERN = re.compile(
    r"^\s*【\s*(例|例题|典例|变式|练习)\s*"
    r"([0-9一二三四五六七八九十]{1,4}(?:[-－—][0-9一二三四五六七八九十]{1,4})?)"
    r"\s*】\s*"
)
OPTION_LABEL_PATTERN = re.compile(r"^\s*[A-H][\.．、:：]\s+")
VISUAL_CUE_PATTERN = re.compile(
    r"(如图|下图|图中|图示|函数图像|坐标系|表格|统计图|几何图)"
)
MID_TEXT_QUESTION_HINT = re.compile(
    r"[。，；\s](?:第\s*)?([0-9]{1,3})(?:\s*题)?[\.．、)]\s*\S"
)

# ADR 012: Instruction/preamble cues that suggest a numbered item is NOT a real question
INSTRUCTION_CUES = (
    "答题前", "考生须知", "注意事项", "本试卷", "本卷",
    "考试时间", "满分", "答案写在答题卡", "用2B铅笔", "用 2B 铅笔",
    "不准使用", "考试结束后", "选择题作答", "非选择题必须",
    "将答案写在", "答题卡上", "写在试卷上", "试卷满分",
    "考试用时", "考生务必将", "务必", "每小题", "本卷共",
    "参考公式", "答案标号", "涂黑", "黑色墨水", "钢笔或签字笔",
    "用铅笔",
)

STRONG_INSTRUCTION_CUES = (
    "答题前", "考生须知", "注意事项", "每小题", "参考公式",
    "答案标号", "涂黑", "黑色墨水", "钢笔或签字笔", "答题卡上",
    "将答案写在", "写在试卷上", "用2B铅笔", "用 2B 铅笔", "用铅笔",
)

# ADR 012: Math content features that suggest a numbered item IS a real question
MATH_FEATURES = (
    "已知", "设", "若", "求", "证明", "计算", "函数",
    "数列", "集合", "方程", "不等式", "概率", "椭圆",
    "双曲线", "抛物线", "向量", "三角形", "圆",
    "$", "∠", "△", "⊙", "∥", "⊥", "≤", "≥", "≠",
    "°", "′", "″", "α", "β", "γ", "θ", "π",
    "sin", "cos", "tan", "log",
)

ALLOWED_ELEMENT_TYPES = frozenset({
    "text", "formula", "image", "table", "figure", "line", "header", "footer",
})

ASSET_TYPES = frozenset({"image", "table", "figure"})

# ---------------------------------------------------------------------------
# Output types (ADR 001 Output Contract)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class AssetAssignment:
    asset_id: str
    score: float
    reasons: list[str]
    needs_review: bool


@dataclass(slots=True)
class LayoutOwnershipBlock:
    question_block_id: str
    question_number: str
    section_title: str
    pages: list[int]
    column_index: int
    text_bbox: list[float]
    question_bbox: list[float]
    element_ids: list[str]
    assets: list[AssetAssignment]
    warnings: list[str]
    section_path: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Internal element representation
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Element:
    id: str
    page: int
    type: str
    bbox: tuple[float, float, float, float]
    text: str
    confidence: float
    # computed during processing
    width: float = 0.0
    height: float = 0.0
    x_center: float = 0.0
    column_index: int = -1
    is_noise: bool = False
    is_header_footer: bool = False
    is_section: bool = False
    is_answer_section: bool = False
    is_question_anchor: bool = False
    question_number: str = ""
    section_title: str = ""
    section_path: tuple[str, ...] = ()
    reading_order: int = -1
    is_option_label: bool = False


# ---------------------------------------------------------------------------
# Step 1: Normalize and validate
# ---------------------------------------------------------------------------

def normalize_elements(raw_elements: list[dict[str, Any]]) -> tuple[list[_Element], list[str]]:
    elements: list[_Element] = []
    warnings: list[str] = []

    for raw in raw_elements:
        eid = raw.get("id")
        page = raw.get("page")
        etype = raw.get("type")
        bbox = raw.get("bbox")
        text = raw.get("text", "") or ""

        if eid is None:
            warnings.append("invalid_layout_element: missing id")
            continue
        if page is None or not isinstance(page, int) or page < 1:
            warnings.append(f"invalid_layout_element: {eid} missing or invalid page")
            continue
        if etype not in ALLOWED_ELEMENT_TYPES:
            warnings.append(f"invalid_layout_element: {eid} invalid type {etype!r}")
            continue
        if not isinstance(bbox, list | tuple) or len(bbox) != 4:
            warnings.append(f"invalid_layout_element: {eid} invalid bbox")
            continue

        x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        if x2 <= x1 or y2 <= y1:
            warnings.append(f"invalid_layout_element: {eid} invalid bbox dimensions")
            continue

        confidence = float(raw.get("confidence", 1.0)) if raw.get("confidence") is not None else 1.0

        elem = _Element(
            id=str(eid),
            page=page,
            type=str(etype),
            bbox=(x1, y1, x2, y2),
            text=str(text),
            confidence=confidence,
            width=x2 - x1,
            height=y2 - y1,
            x_center=(x1 + x2) / 2.0,
        )
        elements.append(elem)

    return elements, warnings


# ---------------------------------------------------------------------------
# Step 2: Preprocessing (noise drop + header/footer detection)
# ---------------------------------------------------------------------------

def preprocess_elements(elements: list[_Element]) -> list[str]:
    """Mark noise elements and detect repeated headers/footers. Returns warning strings."""
    warnings: list[str] = []

    # Noise drop
    for elem in elements:
        if elem.height < 0.006 and elem.width < 0.01:
            elem.is_noise = True
        elif elem.bbox[3] < 0.04:  # y2 < 0.04
            elem.is_noise = True
        elif elem.bbox[1] > 0.96:  # y1 > 0.96
            elem.is_noise = True

    # Repeated header/footer detection
    text_page_map: dict[str, list[tuple[_Element, int]]] = {}
    for elem in elements:
        if elem.is_noise:
            continue
        if elem.type not in ("text", "formula"):
            continue
        norm = elem.text.strip()
        if not norm:
            continue
        text_page_map.setdefault(norm, []).append((elem, elem.page))

    header_footer_candidates: set[str] = set()
    for norm_text, occurrences in text_page_map.items():
        pages_seen = {p for _, p in occurrences}
        if len(pages_seen) >= 3:
            for elem, _ in occurrences:
                y1, y2 = elem.bbox[1], elem.bbox[3]
                if y2 < 0.08 or y1 > 0.92:
                    header_footer_candidates.add(elem.id)

    for elem in elements:
        if elem.id in header_footer_candidates:
            elem.is_header_footer = True

    return warnings


# ---------------------------------------------------------------------------
# Step 3: Column detection (per page)
# ---------------------------------------------------------------------------

def detect_columns(elements: list[_Element]) -> dict[int, list[dict[str, Any]]]:
    """Return per-page column definitions. column = {index, x1, x2, y1, y2}.

    Mutates each element's column_index in place.
    """
    pages: dict[int, list[_Element]] = {}
    for elem in elements:
        if elem.is_noise or elem.is_header_footer:
            continue
        pages.setdefault(elem.page, []).append(elem)

    page_columns: dict[int, list[dict[str, Any]]] = {}

    for page_num, page_elements in sorted(pages.items()):
        eligible = [
            e for e in page_elements
            if e.type in ("text", "formula") and e.width < 0.75
        ]
        if not eligible:
            # single column default
            columns = [{"index": 0, "x1": 0.0, "x2": 1.0, "y1": 0.0, "y2": 1.0}]
            page_columns[page_num] = columns
            continue

        eligible.sort(key=lambda e: e.x_center)
        x_centers = [e.x_center for e in eligible]
        gaps = [x_centers[i + 1] - x_centers[i] for i in range(len(x_centers) - 1)]

        if not gaps:
            columns_data = [{"index": 0, "x1": 0.0, "x2": 1.0, "y1": 0.0, "y2": 1.0}]
            page_columns[page_num] = columns_data
            continue

        major_gap = max(gaps)

        if major_gap < 0.18:
            # single column: use full width of all eligible
            x1 = min(e.bbox[0] for e in eligible)
            x2 = max(e.bbox[2] for e in eligible)
            columns = [{"index": 0, "x1": x1, "x2": x2, "y1": 0.0, "y2": 1.0}]
        else:
            # multi-column: split at gaps >= 0.18
            split_indices = [i for i, g in enumerate(gaps) if g >= 0.18]
            clusters: list[list[_Element]] = []
            start = 0
            for si in split_indices:
                clusters.append(eligible[start:si + 1])
                start = si + 1
            clusters.append(eligible[start:])
            columns = []
            for idx, cluster in enumerate(clusters):
                cx1 = min(e.bbox[0] for e in cluster)
                cx2 = max(e.bbox[2] for e in cluster)
                columns.append({"index": idx, "x1": cx1, "x2": cx2, "y1": 0.0, "y2": 1.0})

        page_columns[page_num] = columns

    # Assign every non-noise element to best column
    for elem in elements:
        if elem.is_noise:
            continue
        cols = page_columns.get(elem.page, [])
        if not cols:
            elem.column_index = -1
            continue

        best_col = -1
        best_overlap = -1.0
        for col in cols:
            overlap = _horizontal_overlap(elem.bbox, (col["x1"], col["y1"], col["x2"], col["y2"]))
            if overlap > best_overlap:
                best_overlap = overlap
                best_col = col["index"]
        elem.column_index = best_col

    return page_columns


# ---------------------------------------------------------------------------
# Step 4: Reading order
# ---------------------------------------------------------------------------

def assign_reading_order(elements: list[_Element]) -> list[_Element]:
    """Sort elements by page, column_index, y1, x1. Mutates reading_order in place."""
    active = [e for e in elements if not e.is_noise]

    def _sort_key(e: _Element) -> tuple[int, int, float, float]:
        return (e.page, e.column_index if e.column_index >= 0 else 0, e.bbox[1], e.bbox[0])

    active.sort(key=_sort_key)
    for idx, elem in enumerate(active):
        elem.reading_order = idx
    return active


# ---------------------------------------------------------------------------
# Step 5: Section detection
# ---------------------------------------------------------------------------

def detect_sections(elements: list[_Element]) -> list[str]:
    """Mark section and answer-section elements. Build hierarchical section_path.

    ADR 002: replaces flat section_title propagation with nested section_path.
    Section elements get section_path set directly; non-section elements inherit
    the path later in build_question_blocks() via reading-order propagation.
    """
    warnings: list[str] = []
    current_path: list[str] = []

    for elem in elements:
        if elem.is_noise or elem.is_header_footer:
            continue
        text = elem.text.strip()
        if not text:
            continue

        if ANSWER_SECTION_PATTERN.match(text):
            elem.is_answer_section = True
            current_path = ["参考答案"]
            continue

        if ALT_SECTION_PATTERN.match(text):
            elem.is_section = True
            elem.section_title = text
            current_path = [text]
            elem.section_path = tuple(current_path)
            continue

        if SECTION_PATTERN.match(text):
            elem.is_section = True
            elem.section_title = text
            if current_path and NONSTANDARD_SUBSECTION_PATTERN.search(current_path[-1]):
                current_path = [current_path[0], text]
            else:
                current_path = [text]
            elem.section_path = tuple(current_path)
            continue

        # Non-section elements get a snapshot of the current section title
        # for backward compat; section_path is resolved in build_question_blocks.
        elem.section_title = current_path[-1] if current_path else ""

    return warnings


# ---------------------------------------------------------------------------
# Step 6: Question anchor detection
# ---------------------------------------------------------------------------

def detect_question_anchors(
    elements: list[_Element],
    page_columns: dict[int, list[dict[str, Any]]],
    sorted_elements: list[_Element],
) -> tuple[list[_Element], list[str]]:
    """Identify question anchor elements. Returns (anchors, warnings)."""
    warnings: list[str] = []

    # Build answer-section range: once answer section starts, elements after are excluded
    answer_section_pages: set[int] = set()
    in_answer = False
    answer_start_orders: list[int] = []

    for elem in sorted_elements:
        if elem.is_answer_section:
            in_answer = True
            answer_start_orders.append(elem.reading_order)
            answer_section_pages.add(elem.page)

    # Mark option labels
    for elem in elements:
        if elem.is_noise or elem.is_header_footer:
            continue
        if elem.type not in ("text", "formula"):
            continue
        if OPTION_LABEL_PATTERN.match(elem.text.strip()):
            elem.is_option_label = True

    anchors: list[_Element] = []
    seen_numbers: dict[str, list[_Element]] = {}
    lecture_anchor_orders = [
        elem.reading_order
        for elem in sorted_elements
        if elem.type in ("text", "formula") and LECTURE_QUESTION_PATTERN.match(elem.text.strip())
    ]
    first_lecture_anchor_order = min(lecture_anchor_orders) if lecture_anchor_orders else None

    for elem in sorted_elements:
        if elem.is_noise or elem.is_header_footer:
            continue
        if elem.is_section or elem.is_answer_section:
            continue
        if elem.is_option_label:
            continue
        if elem.type not in ("text", "formula"):
            continue

        # in answer section range
        if in_answer and answer_start_orders and elem.reading_order >= answer_start_orders[0]:
            continue

        text = elem.text.strip()
        if not text:
            continue

        marker_end = 0
        is_lecture_anchor = False

        lecture_match = LECTURE_QUESTION_PATTERN.match(text)
        if lecture_match:
            label = lecture_match.group(1)
            suffix = lecture_match.group(2).replace("－", "-").replace("—", "-")
            q_number = f"{label}{suffix}"
            marker_end = lecture_match.end()
            is_lecture_anchor = True
        else:
            # Try Arabic number first
            match = QUESTION_ARABIC_PATTERN.match(text)
            if match:
                q_number = match.group(1)
                marker_end = match.end()
            else:
                # Try Chinese number
                match = QUESTION_CHINESE_PATTERN.match(text)
                if match:
                    q_number = match.group(1)
                    marker_end = match.end()
                else:
                    continue

        # Anchor acceptance: x1 <= column.x1 + 0.12
        cols = page_columns.get(elem.page, [])
        if elem.column_index >= 0 and elem.column_index < len(cols):
            col = cols[elem.column_index]
            if elem.bbox[0] > col["x1"] + 0.12:
                continue

        # Reject decimal numbers (e.g. "0.005", "3.14") that match the pattern
        if not is_lecture_anchor and text[marker_end:marker_end + 1].isdigit():
            continue

        # text after marker check
        remainder = text[marker_end:].strip()

        if (
            first_lecture_anchor_order is not None
            and elem.reading_order < first_lecture_anchor_order
            and not is_lecture_anchor
        ):
            warnings.append(
                f"knowledge_note_number_filtered: {q_number} at {elem.id} "
                f"appears before first lecture example, not a question"
            )
            continue

        # ADR 017: numbered instructions can appear before any paper part, not
        # only before the first formal section.
        combined = remainder if remainder else text
        if _is_instruction_number(elem.text, combined):
            warnings.append(
                f"instruction_number_filtered: {q_number} at {elem.id} "
                f"looks like instruction/preamble, not a real question"
            )
            continue

        if remainder:
            elem.question_number = q_number
            elem.is_question_anchor = True
            anchors.append(elem)
            seen_numbers.setdefault(q_number, []).append(elem)
        else:
            # Check next element vertical gap
            next_elem = _next_in_reading_order(elem, sorted_elements)
            if next_elem and next_elem.page == elem.page:
                vertical_gap = next_elem.bbox[1] - elem.bbox[3]
                if vertical_gap <= 0.035:
                    elem.question_number = q_number
                    elem.is_question_anchor = True
                    anchors.append(elem)
                    seen_numbers.setdefault(q_number, []).append(elem)

    return anchors, warnings


# ---------------------------------------------------------------------------
# Step 7: Block boundary & Step 8: Text ownership (combined)
# ---------------------------------------------------------------------------

MAX_PAGES_PER_QUESTION = 3


def build_question_blocks(
    paper_id: str,
    anchors: list[_Element],
    sorted_elements: list[_Element],
    elements_by_id: dict[str, _Element],
    page_columns: dict[int, list[dict[str, Any]]],
) -> tuple[list[LayoutOwnershipBlock], list[str]]:
    """Build question ownership blocks and assign text/formula ownership."""
    warnings: list[str] = []
    blocks: list[LayoutOwnershipBlock] = []

    # Determine where answer section starts (reading order)
    answer_start_order: int | None = None
    for elem in sorted_elements:
        if elem.is_answer_section:
            answer_start_order = elem.reading_order
            break

    # Section tracking: section_starts records (reading_order, section_title, section_path)
    section_starts: list[tuple[int, str, tuple[str, ...]]] = []
    for elem in sorted_elements:
        if elem.is_section and elem.section_title:
            sp = elem.section_path if elem.section_path else (elem.section_title,)
            section_starts.append((elem.reading_order, elem.section_title, sp))

    if not anchors:
        return blocks, warnings

    seen_numbers: dict[tuple[tuple[str, ...], str], int] = {}  # (section_path, q_number) -> count

    for i, anchor in enumerate(anchors):
        q_number = anchor.question_number

        # Find current section (title + path) from reading-order propagation
        current_section, current_path = _current_section_for(anchor.reading_order, section_starts)

        # Dedup key: (section_path, question_number) per ADR 002
        scope_key = (current_path, q_number)
        if scope_key in seen_numbers:
            seen_numbers[scope_key] += 1
            warnings.append(
                f"duplicate_question_number: {q_number} appears at anchor {anchor.id} "
                f"in section_path {current_path}"
            )
        else:
            seen_numbers[scope_key] = 1

        # Determine end boundary
        # Find next anchor in same page+column
        next_anchor_order: int | None = None
        for j in range(i + 1, len(anchors)):
            na = anchors[j]
            if na.page == anchor.page and na.column_index == anchor.column_index:
                next_anchor_order = na.reading_order
                break

        # If no next anchor on same page+column, check cross-page
        pages_covered: list[int] = [anchor.page]
        cross_page = False
        bound_order = next_anchor_order
        effective_column = anchor.column_index

        if next_anchor_order is None and i + 1 < len(anchors):
            # Try cross-page continuation to next anchor
            next_a = anchors[i + 1]
            if next_a.page > anchor.page:
                cross_page = True
                if next_a.page - anchor.page + 1 > MAX_PAGES_PER_QUESTION:
                    warnings.append(f"question_spans_too_many_pages: question {q_number} exceeds {MAX_PAGES_PER_QUESTION} pages")
                    bound_order = next_a.reading_order
                else:
                    bound_order = next_a.reading_order
                    pages_covered = list(range(anchor.page, next_a.page + 1))

                    # Cross-page column mismatch detection
                    for pg in range(anchor.page + 1, next_a.page + 1):
                        pg_cols = page_columns.get(pg, [])
                        if pg_cols:
                            # Check if same-index column exists
                            if effective_column < len(pg_cols):
                                continue  # same-index column exists, use it
                            # Find nearest column by x-overlap from anchor's column on anchor.page
                            anchor_cols = page_columns.get(anchor.page, [])
                            if anchor_cols and effective_column < len(anchor_cols):
                                anchor_col = anchor_cols[effective_column]
                                anchor_col_bbox = (anchor_col["x1"], anchor_col["y1"],
                                                   anchor_col["x2"], anchor_col["y2"])
                                best_col_idx = -1
                                best_overlap = -1.0
                                for ci, col in enumerate(pg_cols):
                                    col_bbox = (col["x1"], col["y1"], col["x2"], col["y2"])
                                    overlap = _horizontal_overlap(anchor_col_bbox, col_bbox)
                                    if overlap > best_overlap:
                                        best_overlap = overlap
                                        best_col_idx = ci
                                if best_overlap < 0.35:
                                    warnings.append(
                                        f"cross_page_column_mismatch: question {q_number} "
                                        f"column {effective_column} on page {anchor.page} "
                                        f"has low overlap ({best_overlap:.3f}) with best column on page {pg}"
                                    )
                                effective_column = best_col_idx if best_col_idx >= 0 else effective_column

        # Clamp to answer section
        if answer_start_order is not None:
            if bound_order is None or answer_start_order < bound_order:
                bound_order = answer_start_order

        # Collect owned text/formula elements in reading order
        owned_element_ids: list[str] = []
        text_bbox_elements: list[tuple[float, float, float, float]] = []

        for elem in sorted_elements:
            if elem.reading_order < anchor.reading_order:
                continue
            if elem.is_noise or elem.is_header_footer:
                continue
            if elem.is_answer_section:
                continue
            if elem.is_section and elem.reading_order > anchor.reading_order:
                # Stop at next section
                if bound_order is None or elem.reading_order < bound_order:
                    bound_order = elem.reading_order
                break

            if bound_order is not None and elem.reading_order >= bound_order:
                break

            # Cross-page: include elements on pages between anchor and bound
            if cross_page and elem.page not in pages_covered:
                continue
            if cross_page and elem.page != anchor.page and elem.column_index != effective_column:
                continue

            # Non-cross-page: only same page+column
            if not cross_page and (elem.page != anchor.page or elem.column_index != anchor.column_index):
                continue

            if elem.type in ("text", "formula") and not elem.is_section:
                owned_element_ids.append(elem.id)
                text_bbox_elements.append(elem.bbox)

        if not owned_element_ids:
            warnings.append(f"question_without_text: question {q_number} has no owned text elements")

        # Compute text_bbox
        if text_bbox_elements:
            text_bbox = _union_bbox(text_bbox_elements)
        else:
            text_bbox = list(anchor.bbox)

        # Compute block
        block_id = _build_block_id(paper_id, anchors, i)
        block = LayoutOwnershipBlock(
            question_block_id=block_id,
            question_number=q_number,
            section_title=current_section,
            section_path=current_path,
            pages=sorted(set(pages_covered)),
            column_index=effective_column if effective_column >= 0 else 0,
            text_bbox=text_bbox,
            question_bbox=list(text_bbox),  # will include assets later
            element_ids=list(owned_element_ids),
            assets=[],
            warnings=[],
        )
        blocks.append(block)

    return blocks, warnings


# ---------------------------------------------------------------------------
# Step 9: Asset scoring and assignment
# ---------------------------------------------------------------------------

def assign_assets(
    blocks: list[LayoutOwnershipBlock],
    elements: list[_Element],
    elements_by_id: dict[str, _Element],
    page_columns: dict[int, list[dict[str, Any]]],
) -> list[str]:
    """Score and assign visual assets (image/table/figure) to question blocks."""
    warnings: list[str] = []

    asset_elements = [e for e in elements if e.type in ASSET_TYPES and not e.is_noise]

    for asset in asset_elements:
        scores: list[tuple[float, int, list[str]]] = []  # (score, block_index, reasons)

        for bi, block in enumerate(blocks):
            score, reasons = _score_asset_for_block(asset, block, elements_by_id, page_columns)
            scores.append((score, bi, reasons))

        if not scores:
            warnings.append(f"unassigned_visual_asset: {asset.id} could not be assigned to any question")
            continue

        scores.sort(key=lambda x: x[0], reverse=True)
        top_score, top_bi, top_reasons = scores[0]

        # Conflict detection: top2 gap < 0.12
        if len(scores) >= 2:
            second_score = scores[1][0]
            if top_score - second_score < 0.12:
                warnings.append(
                    f"asset_assignment_conflict: {asset.id} top scores {top_score:.3f} vs {second_score:.3f} gap < 0.12"
                )

        # Assignment thresholds
        if top_score >= 0.62:
            needs_review = False
        elif top_score >= 0.45:
            needs_review = True
            warnings.append(
                f"low_confidence_asset_assignment: {asset.id} to question {blocks[top_bi].question_number} score={top_score:.3f}"
            )
        else:
            warnings.append(f"unassigned_visual_asset: {asset.id} best score {top_score:.3f} < 0.45")
            continue

        blocks[top_bi].assets.append(
            AssetAssignment(
                asset_id=asset.id,
                score=round(top_score, 4),
                reasons=top_reasons,
                needs_review=needs_review,
            )
        )

        # Update question_bbox to include asset
        asset_bbox_list = list(asset.bbox)
        blocks[top_bi].question_bbox = _union_bbox_list(
            [blocks[top_bi].question_bbox, asset_bbox_list]
        )

    return warnings


def _score_asset_for_block(
    asset: _Element,
    block: LayoutOwnershipBlock,
    elements_by_id: dict[str, _Element],
    page_columns: dict[int, list[dict[str, Any]]],
) -> tuple[float, list[str]]:
    """Score an asset against a question block. Returns (score, reasons)."""
    reasons: list[str] = []

    # same_page_score
    same_page_score = 1.0 if asset.page in block.pages else 0.0
    if same_page_score > 0:
        reasons.append("same_page")

    # vertical_score: y_overlap with text_bbox expanded by 0.04
    expanded_text_bbox = (
        block.text_bbox[0],
        max(0.0, block.text_bbox[1] - 0.04),
        block.text_bbox[2],
        min(1.0, block.text_bbox[3] + 0.04),
    )
    vertical_score = _y_overlap(asset.bbox, expanded_text_bbox)
    if vertical_score > 0:
        reasons.append("vertical_near")

    # column_score
    cols = page_columns.get(asset.page, [])
    if block.column_index < len(cols):
        col = cols[block.column_index]
        col_bbox = (col["x1"], col["y1"], col["x2"], col["y2"])
        column_score = _horizontal_overlap(asset.bbox, col_bbox)
    else:
        column_score = 1.0

    # Cross-column exception: wide asset with vertical overlap
    asset_width = asset.bbox[2] - asset.bbox[0]
    expanded_text_06 = (
        block.text_bbox[0],
        max(0.0, block.text_bbox[1] - 0.06),
        block.text_bbox[2],
        min(1.0, block.text_bbox[3] + 0.06),
    )
    if asset_width > 0.55 and _y_overlap(asset.bbox, expanded_text_06) > 0:
        column_score = 1.0
        reasons.append("cross_column")

    if column_score > 0:
        reasons.append("same_column" if column_score >= 0.5 else "partial_column")

    # distance_score
    vertical_gap = _vertical_gap_score(asset.bbox, block.text_bbox)
    distance_score = math.exp(-vertical_gap / 0.08)
    if distance_score > 0.5:
        reasons.append("proximity")

    # cue_score
    cue_score = 0.0
    for eid in block.element_ids:
        elem = elements_by_id.get(eid)
        if elem and VISUAL_CUE_PATTERN.search(elem.text):
            cue_score = 1.0
            reasons.append("visual_cue")
            break

    score = (
        0.35 * same_page_score
        + 0.25 * vertical_score
        + 0.20 * column_score
        + 0.15 * distance_score
        + 0.05 * cue_score
    )
    return score, reasons


# ---------------------------------------------------------------------------
# Step 10: Bbox calculation is done inline during block building + asset assignment
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Post-anchor detection: missing_anchor_suspected
# ---------------------------------------------------------------------------


def _detect_missing_anchors(
    elements: list[_Element],
    sorted_elements: list[_Element],
    anchors: list[_Element],
) -> list[str]:
    """Scan non-anchor text elements for embedded question-number patterns
    that suggest OCR merged a question anchor into the previous line."""
    warnings: list[str] = []
    anchor_ids = {a.id for a in anchors}

    in_answer = False
    answer_start_order: int | None = None
    for elem in sorted_elements:
        if elem.is_answer_section:
            in_answer = True
            if answer_start_order is None:
                answer_start_order = elem.reading_order
            break

    for elem in sorted_elements:
        if elem.id in anchor_ids:
            continue
        if elem.is_noise or elem.is_header_footer:
            continue
        if elem.is_section or elem.is_answer_section or elem.is_option_label:
            continue
        if elem.type not in ("text", "formula"):
            continue
        if in_answer and answer_start_order is not None and elem.reading_order >= answer_start_order:
            continue

        text = elem.text.strip()
        if not text:
            continue

        if MID_TEXT_QUESTION_HINT.search(text):
            warnings.append(
                f"missing_anchor_suspected: {elem.id} contains embedded question number"
            )

    return warnings


# ---------------------------------------------------------------------------
# Post-ownership detection: orphan formulas + cross-column text drift
# ---------------------------------------------------------------------------


def _detect_orphan_and_cross_column(
    blocks: list[LayoutOwnershipBlock],
    elements: list[_Element],
    sorted_elements: list[_Element],
) -> list[str]:
    """Detect formula elements not owned by any block, and text elements that
    drifted across columns. Returns warnings."""
    warnings: list[str] = []
    owned_ids: set[str] = set()
    for b in blocks:
        owned_ids.update(b.element_ids)

    for elem in sorted_elements:
        if elem.is_noise or elem.is_header_footer:
            continue
        if elem.is_section or elem.is_answer_section:
            continue

        if elem.id in owned_ids:
            continue

        if elem.type == "formula":
            warnings.append(f"orphan_formula: {elem.id} not owned by any question block")
            continue

        if elem.type == "text":
            # Check if this unowned text element overlaps a block's y-range
            # on the same page but has a different column_index → cross_column_question
            for block in blocks:
                if elem.page not in block.pages:
                    continue
                if not block.text_bbox:
                    continue
                if elem.column_index == block.column_index:
                    continue
                text_y1, text_y2 = block.text_bbox[1], block.text_bbox[3]
                elem_y1, elem_y2 = elem.bbox[1], elem.bbox[3]
                y_overlap = max(0.0, min(elem_y2, text_y2) - max(elem_y1, text_y1))
                if y_overlap > 0:
                    warnings.append(
                        f"cross_column_question: {elem.id} on page {elem.page} "
                        f"overlaps question {block.question_number} y-range but is in column {elem.column_index} "
                        f"(question column {block.column_index})"
                    )
                    break

    return warnings


def _detect_section_hierarchy_issues(
    blocks: list[LayoutOwnershipBlock],
    elements: list[_Element],
) -> list[str]:
    """Detect nonstandard section nesting by analyzing question number collisions.

    ADR 002: after nesting resolution, the warning fires only when the SAME
    question_number still collides under the SAME section_path (i.e. nesting
    did not resolve the collision). Different section_paths with the same
    number are expected behavior in nested-section papers.
    """
    from collections import defaultdict

    # First, check if this paper has nonstandard section markers at all.
    has_nonstandard = any(
        e.is_section
        and not SECTION_PATTERN.match(e.text.strip())
        and NONSTANDARD_SUBSECTION_PATTERN.search(e.text.strip())
        for e in elements
    )
    if not has_nonstandard:
        return []

    # Group blocks by question_number
    by_number: dict[str, list[LayoutOwnershipBlock]] = defaultdict(list)
    for b in blocks:
        by_number[b.question_number].append(b)

    # Find numbers appearing >= 3 times where section_path does NOT explain
    # the collision (i.e. same path appears for multiple blocks of same number).
    suspected_numbers: list[str] = []
    for qn, qn_blocks in by_number.items():
        if len(qn_blocks) < 3:
            continue
        paths = {b.section_path for b in qn_blocks}
        if len(paths) != len(qn_blocks):
            # Some blocks share the same section_path → hierarchy didn't resolve
            suspected_numbers.append(qn)

    if not suspected_numbers:
        return []

    # Build a structured warning
    suspected_numbers.sort(key=lambda n: (int(n) if n.isdigit() else 0, n))
    affected_paths: set[str] = set()
    for qn in suspected_numbers:
        for b in by_number[qn]:
            affected_paths.add(str(b.section_path))

    summary = (
        f"section_hierarchy_suspected: "
        f"{len(suspected_numbers)} question numbers appear >= 3 times "
        f"across {len(affected_paths)} unresolved section paths "
        f"(numbers: {', '.join(suspected_numbers[:10])}"
        f"{'...' if len(suspected_numbers) > 10 else ''})"
    )
    return [summary]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def layout_ownership(
    paper_id: str,
    raw_elements: list[dict[str, Any]],
) -> list[LayoutOwnershipBlock]:
    """Convert MinerU layout elements into question ownership blocks.

    Follows ADR 001: deterministic, no DeepSeek, no DB, no UI.
    """
    all_warnings: list[str] = []

    # Step 1: Normalize
    elements, warnings = normalize_elements(raw_elements)
    all_warnings.extend(warnings)
    if not elements:
        return []

    elements_by_id: dict[str, _Element] = {e.id: e for e in elements}

    # Step 2: Preprocess
    pre_warnings = preprocess_elements(elements)
    all_warnings.extend(pre_warnings)

    # Step 3: Column detection
    page_columns = detect_columns(elements)

    # Step 4: Reading order
    sorted_elements = assign_reading_order(elements)

    # Step 5: Section detection
    sec_warnings = detect_sections(elements)
    all_warnings.extend(sec_warnings)

    # Step 6: Question anchor detection
    anchors, anchor_warnings = detect_question_anchors(elements, page_columns, sorted_elements)
    all_warnings.extend(anchor_warnings)
    # 6b: missing_anchor_suspected — OCR-merged question numbers
    missing_warnings = _detect_missing_anchors(elements, sorted_elements, anchors)
    all_warnings.extend(missing_warnings)

    # Step 7-8: Build question blocks with text ownership
    blocks, block_warnings = build_question_blocks(
        paper_id, anchors, sorted_elements, elements_by_id, page_columns,
    )
    all_warnings.extend(block_warnings)

    # 8b: orphan formula + cross-column text drift detection
    orphan_warnings = _detect_orphan_and_cross_column(blocks, elements, sorted_elements)
    all_warnings.extend(orphan_warnings)

    # 8c: section hierarchy analysis — detect nested subsections that cause
    # question number collisions across nonstandard section boundaries
    hierarchy_warnings = _detect_section_hierarchy_issues(blocks, elements)
    all_warnings.extend(hierarchy_warnings)

    # Step 9: Asset scoring and assignment
    asset_warnings = assign_assets(blocks, elements, elements_by_id, page_columns)
    all_warnings.extend(asset_warnings)

    # Attach global warnings to relevant blocks
    _distribute_warnings(blocks, all_warnings, anchors)

    return blocks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _horizontal_overlap(
    bbox: tuple[float, float, float, float],
    ref: tuple[float, float, float, float],
) -> float:
    x1, _, x2, _ = bbox
    rx1, _, rx2, _ = ref
    overlap = max(0.0, min(x2, rx2) - max(x1, rx1))
    bbox_width = x2 - x1
    if bbox_width <= 0:
        return 0.0
    return overlap / bbox_width


def _y_overlap(
    bbox: tuple[float, float, float, float],
    ref: tuple[float, float, float, float],
) -> float:
    _, y1, _, y2 = bbox
    _, ry1, _, ry2 = ref
    overlap = max(0.0, min(y2, ry2) - max(y1, ry1))
    bbox_height = y2 - y1
    if bbox_height <= 0:
        return 0.0
    return overlap / bbox_height


def _vertical_gap_score(
    bbox: tuple[float, float, float, float],
    ref: tuple[float, float, float, float],
) -> float:
    """Minimum vertical distance between two bboxes."""
    _, y1, _, y2 = bbox
    _, ry1, _, ry2 = ref
    if y2 <= ry1:
        return ry1 - y2
    if ry2 <= y1:
        return y1 - ry2
    return 0.0


def _union_bbox(bboxes: list[tuple[float, float, float, float]]) -> list[float]:
    if not bboxes:
        return [0.0, 0.0, 0.0, 0.0]
    x1 = min(b[0] for b in bboxes)
    y1 = min(b[1] for b in bboxes)
    x2 = max(b[2] for b in bboxes)
    y2 = max(b[3] for b in bboxes)
    return [x1, y1, x2, y2]


def _union_bbox_list(bboxes: list[list[float]]) -> list[float]:
    if not bboxes:
        return [0.0, 0.0, 0.0, 0.0]
    x1 = min(b[0] for b in bboxes)
    y1 = min(b[1] for b in bboxes)
    x2 = max(b[2] for b in bboxes)
    y2 = max(b[3] for b in bboxes)
    return [x1, y1, x2, y2]


def _next_in_reading_order(
    elem: _Element,
    sorted_elements: list[_Element],
) -> _Element | None:
    for i, e in enumerate(sorted_elements):
        if e.id == elem.id and i + 1 < len(sorted_elements):
            return sorted_elements[i + 1]
    return None


def _is_instruction_number(full_text: str, question_text: str) -> bool:
    """ADR 012: check if a number-matched element is instruction/preamble.

    Returns True if the text contains instruction cues AND lacks math features,
    meaning it should be filtered out (not treated as a real question anchor).
    """
    search_text = full_text + " " + question_text
    has_cue = any(cue in search_text for cue in INSTRUCTION_CUES)
    if not has_cue:
        return False
    if any(cue in search_text for cue in STRONG_INSTRUCTION_CUES):
        return not _has_problem_action(search_text)
    has_math = _has_math_feature(search_text)
    return not has_math


def _has_problem_action(text: str) -> bool:
    """Return True for action verbs that make an item look like an actual problem."""
    if any(token in text for token in ("已知", "证明", "计算", "解答")):
        return True
    if re.search(r"(?<!要)求(?!作答|填写|涂|改|交|使用)", text):
        return True
    if re.search(r"设(?!置|备|施|计)", text):
        return True
    if re.search(r"若(?!干)", text):
        return True
    return False


def _looks_like_knowledge_note_number(text: str) -> bool:
    """Return True for numbered definition notes in lecture handouts."""
    compact = re.sub(r"\s+", "", text)
    has_note_cue = any(cue in compact for cue in KNOWLEDGE_NOTE_CUES)
    has_action_cue = any(cue in compact for cue in QUESTION_ACTION_CUES)
    return has_note_cue and not has_action_cue


def _has_math_feature(text: str) -> bool:
    """Return True when text has strong math-question signals.

    Single-character cues such as "求" and "设" are intentionally guarded:
    instruction prose often contains words like "要求" or "设置", which must not
    rescue a preamble item from instruction filtering.
    """
    for feat in MATH_FEATURES:
        if feat == "求":
            if re.search(r"(?<!要)求(?!作答|填写|涂|改|交|使用)", text):
                return True
            continue
        if feat == "设":
            if re.search(r"设(?!置|备|施|计)", text):
                return True
            continue
        if feat in text:
            return True
    return False


def _current_section_for(
    reading_order: int,
    section_starts: list[tuple[int, str, tuple[str, ...]]],
) -> tuple[str, tuple[str, ...]]:
    """Return (section_title, section_path) for the given reading_order."""
    current_title = ""
    current_path: tuple[str, ...] = ()
    for order, title, sp in section_starts:
        if order < reading_order:
            current_title = title
            current_path = sp
        else:
            break
    return current_title, current_path


def _build_block_id(paper_id: str, anchors: list[_Element], index: int) -> str:
    # Try to use the anchor's question number, but sanitize for ID
    q_num = anchors[index].question_number
    safe_num = "".join(c for c in q_num if c.isascii() and c.isalnum() and c != " ")
    if safe_num:
        return f"{paper_id}_qb_{safe_num}"
    return f"{paper_id}_qb_{index + 1:04d}"


def _distribute_warnings(
    blocks: list[LayoutOwnershipBlock],
    all_warnings: list[str],
    anchors: list[_Element],
) -> None:
    """Attach relevant warnings to blocks by matching question number in the
    warning text. Unmatched global warnings (orphan_formula, missing_anchor_suspected,
    etc.) are appended to the first block for visibility."""
    unmatched: list[str] = []
    for w in all_warnings:
        matched = False
        for block in blocks:
            if block.question_number and block.question_number in w:
                block.warnings.append(w)
                matched = True
                break
        if not matched:
            unmatched.append(w)
    # Attach unmatched warnings to the first block so callers can inspect them
    if unmatched and blocks:
        blocks[0].warnings.extend(unmatched)
