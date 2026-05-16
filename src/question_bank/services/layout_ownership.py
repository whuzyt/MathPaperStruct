from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Patterns (ADR 001)
# ---------------------------------------------------------------------------
SECTION_PATTERN = re.compile(
    r"^[一二三四五六七八九十]+[、.．]\s*(选择|填空|解答|计算|证明|应用|综合|压轴).*$"
)
ANSWER_SECTION_PATTERN = re.compile(
    r"^(参考答案|答案|解析|答案与解析|试卷答案|详解)\s*$"
)
QUESTION_ARABIC_PATTERN = re.compile(
    r"^\s*(?:第\s*)?([0-9]{1,3})(?:\s*题)?[\.．、)]\s*"
)
QUESTION_CHINESE_PATTERN = re.compile(
    r"^\s*[（(]?([一二三四五六七八九十]{1,4})[）)、.．]\s*"
)
OPTION_LABEL_PATTERN = re.compile(r"^\s*[A-H][\.．、:：]\s+")
VISUAL_CUE_PATTERN = re.compile(
    r"(如图|下图|图中|图示|函数图像|坐标系|表格|统计图|几何图)"
)
MID_TEXT_QUESTION_HINT = re.compile(
    r"[。，；\s](?:第\s*)?([0-9]{1,3})(?:\s*题)?[\.．、)]\s*\S"
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
    """Mark section and answer-section elements. Returns warnings."""
    warnings: list[str] = []

    for elem in elements:
        if elem.is_noise or elem.is_header_footer:
            continue
        text = elem.text.strip()
        if not text:
            continue

        if ANSWER_SECTION_PATTERN.match(text):
            elem.is_answer_section = True
            continue

        if SECTION_PATTERN.match(text):
            elem.is_section = True
            elem.section_title = text

    return warnings


# ---------------------------------------------------------------------------
# Step 6: Question anchor detection
# ---------------------------------------------------------------------------

def detect_question_anchors(
    elements: list[_Element],
    page_columns: dict[int, list[dict[str, Any]]],
    sorted_elements: list[_Element],
) -> list[_Element]:
    """Identify question anchor elements. Returns list of anchors in reading order."""
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

        # Try Arabic number first
        match = QUESTION_ARABIC_PATTERN.match(text)
        if match:
            q_number = match.group(1)
        else:
            # Try Chinese number
            match = QUESTION_CHINESE_PATTERN.match(text)
            if match:
                q_number = match.group(1)
            else:
                continue

        # Anchor acceptance: x1 <= column.x1 + 0.12
        cols = page_columns.get(elem.page, [])
        if elem.column_index >= 0 and elem.column_index < len(cols):
            col = cols[elem.column_index]
            if elem.bbox[0] > col["x1"] + 0.12:
                continue

        # text after marker check
        remainder = text[match.end():].strip()
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

    return anchors


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

    # Section tracking: current section title in effect
    # Build section start orders
    section_starts: list[tuple[int, str]] = []  # (reading_order, section_title)
    for elem in sorted_elements:
        if elem.is_section and elem.section_title:
            section_starts.append((elem.reading_order, elem.section_title))

    if not anchors:
        return blocks, warnings

    seen_numbers: dict[tuple[str, str], int] = {}  # (section_title, question_number) -> count

    for i, anchor in enumerate(anchors):
        q_number = anchor.question_number

        # Find current section
        current_section = _current_section_for(anchor.reading_order, section_starts)

        # Track duplicate question numbers per section
        scope_key = (current_section, q_number)
        if scope_key in seen_numbers:
            seen_numbers[scope_key] += 1
            warnings.append(
                f"duplicate_question_number: {q_number} appears at anchor {anchor.id} "
                f"in section {current_section!r}"
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
            # Check if this unowned text element overlaps any block's y-range
            # on the same page → cross_column_question
            for block in blocks:
                if elem.page not in block.pages:
                    continue
                if not block.text_bbox:
                    continue
                text_y1, text_y2 = block.text_bbox[1], block.text_bbox[3]
                elem_y1, elem_y2 = elem.bbox[1], elem.bbox[3]
                y_overlap = max(0.0, min(elem_y2, text_y2) - max(elem_y1, text_y1))
                if y_overlap > 0:
                    warnings.append(
                        f"cross_column_question: {elem.id} on page {elem.page} "
                        f"overlaps question {block.question_number} y-range but is in different column"
                    )
                    break

    return warnings


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
    anchors = detect_question_anchors(elements, page_columns, sorted_elements)
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


def _current_section_for(
    reading_order: int,
    section_starts: list[tuple[int, str]],
) -> str:
    current = ""
    for order, title in section_starts:
        if order < reading_order:
            current = title
        else:
            break
    return current


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
