"""ADR 009: Paper Ingestion Orchestrator v1 — End-to-end pipeline coordinator.

Chains existing service modules into a single synchronous ingestion run.
Does NOT reimplement any algorithm — only orchestrates step order, failure
strategy, resume, and report generation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from question_bank.domain.models import Choice, QualityReport, Question, QuestionAsset, QuestionBlock
from question_bank.pipeline import ProcessingResult
from question_bank.services.asset_identity import _Element, identify_raw_assets
from question_bank.services.asset_visual_dedup import generate_visual_asset_candidates
from question_bank.services.duplicate_review import generate_candidate_groups
from question_bank.services.image_phash import compute_phash
from question_bank.services.layout_ownership import LayoutOwnershipBlock, layout_ownership
from question_bank.services.local_asset_store import store_crop_result
from question_bank.services.mineru import LocalMinerURunner, MinerUResult
from question_bank.services.pdf_cropper import crop_pdf_assets
from question_bank.services.quality import (
    GatingResult,
    gate_question,
    validate_question,
)
from question_bank.services.question_identity import QuestionIdentity, fingerprint_blocks
from question_bank.services.question_splitter import (
    parse_answer_entries,
    parse_answer_entry,
    parse_choices,
)
from question_bank.services.type_inference import infer_question_type


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    name: str
    status: str  # success | failed | skipped | warning
    started_at: str
    finished_at: str
    input_count: int = 0
    output_count: int = 0
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class IngestionReport:
    paper_id: str
    status: str  # completed | partial | failed
    started_at: str
    finished_at: str
    steps: list[StepResult]
    counts: dict
    warnings: list[str]
    errors: list[str]
    # ADR 013: quality gating statistics
    questions_passed: int = 0
    questions_warning: int = 0
    questions_failed: int = 0
    failed_question_ids: list[str] = field(default_factory=list)
    quality_warning_counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "paper_id": self.paper_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": [
                {
                    "name": s.name,
                    "status": s.status,
                    "started_at": s.started_at,
                    "finished_at": s.finished_at,
                    "input_count": s.input_count,
                    "output_count": s.output_count,
                    "error": s.error,
                    "warnings": s.warnings,
                }
                for s in self.steps
            ],
            "counts": self.counts,
            "warnings": self.warnings,
            "errors": self.errors,
            "questions_passed": self.questions_passed,
            "questions_warning": self.questions_warning,
            "questions_failed": self.questions_failed,
            "failed_question_ids": self.failed_question_ids,
            "quality_warning_counts": self.quality_warning_counts,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


CRITICAL_STEPS = frozenset({
    "mineru_parse",
    "layout_ownership",
    "deepseek_structure",
    "save_questions",
    "identify_assets",
})


def _make_result(name: str, status: str, started: str, **kwargs) -> StepResult:
    return StepResult(name=name, status=status, started_at=started,
                      finished_at=_now_iso(), **kwargs)


# ---------------------------------------------------------------------------
# Block conversion helpers (LayoutOwnershipBlock → QuestionBlock)
# ---------------------------------------------------------------------------


def _build_block_content(block: LayoutOwnershipBlock,
                         elements_by_id: dict[str, _Element]) -> str:
    """Build text content for a layout ownership block from its elements."""
    parts: list[str] = []
    for eid in block.element_ids:
        elem = elements_by_id.get(eid)
        if elem is None:
            continue
        if elem.type in ("text", "formula", "header", "footer"):
            if elem.text.strip():
                parts.append(elem.text.strip())
        elif elem.type in ("image", "table", "figure"):
            alt = elem.text.strip() if elem.text else f"[{elem.type}]"
            parts.append(alt)
    return "\n\n".join(parts)


def _block_bounding_box(block: LayoutOwnershipBlock,
                        elements_by_id: dict[str, _Element]) -> tuple[float, float, float, float] | None:
    """Compute the bounding box that encloses all elements in a block."""
    xs: list[float] = []
    ys: list[float] = []
    for eid in block.element_ids:
        elem = elements_by_id.get(eid)
        if elem is None:
            continue
        b = elem.bbox
        if len(b) == 4:
            xs.extend((b[0], b[2]))
            ys.extend((b[1], b[3]))
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def _layout_block_to_question_block(
    block: LayoutOwnershipBlock,
    paper_id: str,
    elements_by_id: dict[str, _Element],
) -> QuestionBlock:
    """Convert a LayoutOwnershipBlock to a QuestionBlock for the pipeline."""
    raw_md = _build_block_content(block, elements_by_id)
    pages = sorted({
        elements_by_id[eid].page
        for eid in block.element_ids
        if eid in elements_by_id
    })
    assets: list[QuestionAsset] = []
    for asset in block.assets:
        elem = elements_by_id.get(asset.asset_id)
        if elem is None:
            continue
        assets.append(QuestionAsset(
            id=asset.asset_id,
            type=elem.type,
            storage_url="",
            page=elem.page,
            bbox=elem.bbox,
            confidence=asset.score,
        ))
    return QuestionBlock(
        id=block.question_block_id,
        paper_id=paper_id,
        question_number=block.question_number,
        raw_markdown=raw_md,
        section_title=block.section_path[-1] if block.section_path else "",
        pages=pages if pages else [1],
        bbox=_block_bounding_box(block, elements_by_id),
        assets=assets,
        split_confidence=1.0,
        needs_review=bool(block.warnings),
    )


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def ingest_paper_full(
    paper_id: str,
    pdf_path: str,
    work_dir: str,
    asset_dir: str,
    *,
    dry_run: bool = False,
    resume: bool = False,
    repository=None,
    deepseek_client=None,
    mineru_command: str = "mineru",
) -> IngestionReport:
    started_at = _now_iso()
    steps: list[StepResult] = []
    ctx: dict = {}  # mutable shared state between steps

    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)

    TOTAL_STEPS = 10
    _step_counter = [0]  # mutable counter captured by run() closure

    def run(step_fn, *args, **kwargs):
        _step_counter[0] += 1
        step_name = step_fn.__name__.replace("_step_", "")
        n = _step_counter[0]
        print(f"  [{n}/{TOTAL_STEPS}] {step_name}...", end="", flush=True)
        try:
            result = step_fn(*args, **kwargs)
            steps.append(result)
            print(f" {result.status.upper()}")
            return result
        except Exception as exc:
            steps.append(_make_result(step_name, "failed", _now_iso(), error=str(exc)))
            print(" FAIL")
            return None

    def last_failed_critical() -> bool:
        if not steps:
            return False
        last = steps[-1]
        return last.status == "failed" and last.name in CRITICAL_STEPS

    # Step 1: MinerU parse (critical) — stores MinerUResult in ctx
    run(_step_mineru_parse, paper_id, pdf_path, str(work_path), resume, mineru_command, ctx)
    if last_failed_critical():
        return _finalize(paper_id, started_at, steps, work_path, ctx)

    # Step 2: Layout ownership (critical) — uses paths from ctx + stores blocks
    run(_step_layout_ownership, paper_id, ctx)
    if last_failed_critical():
        return _finalize(paper_id, started_at, steps, work_path, ctx)

    # Step 3: DeepSeek structure (critical) — uses layout blocks from ctx
    run(_step_deepseek_structure, paper_id, deepseek_client, ctx)
    if last_failed_critical():
        return _finalize(paper_id, started_at, steps, work_path, ctx)

    # Step 4: Save questions/blocks (critical) — reads result from ctx
    run(_step_save_questions, paper_id, repository, dry_run, ctx)
    if last_failed_critical():
        return _finalize(paper_id, started_at, steps, work_path, ctx)

    # Step 5: Identify raw assets (critical) — reuses blocks from ctx
    run(_step_identify_assets, paper_id, repository, dry_run, resume, ctx)
    if last_failed_critical():
        return _finalize(paper_id, started_at, steps, work_path, ctx)

    # Step 6: Crop assets (non-critical)
    run(_step_crop_assets, paper_id, pdf_path, asset_dir, repository, dry_run)

    # Step 7: Store assets (non-critical)
    run(_step_store_assets, paper_id, asset_dir, repository, dry_run)

    # Step 8: Compute pHash (non-critical)
    run(_step_compute_phash, paper_id, repository, dry_run)

    # Step 9: Duplicate candidates (non-critical, cross-paper) — uses ctx blocks
    run(_step_duplicate_candidates, paper_id, repository, dry_run, ctx)

    # Step 10: Visual candidates (non-critical, cross-paper)
    run(_step_visual_candidates, repository)

    return _finalize(paper_id, started_at, steps, work_path, ctx)


def _finalize(
    paper_id: str,
    started_at: str,
    steps: list[StepResult],
    work_path: Path,
    ctx: dict | None = None,
) -> IngestionReport:
    warnings: list[str] = []
    errors: list[str] = []

    for s in steps:
        if s.status == "failed":
            if s.name in CRITICAL_STEPS:
                errors.append(f"[{s.name}] {s.error}")
            else:
                warnings.append(f"[{s.name}] {s.error}")
        warnings.extend(s.warnings)

    has_critical = any(s.status == "failed" and s.name in CRITICAL_STEPS for s in steps)
    has_non_critical = any(
        s.status in ("failed", "warning") and s.name not in CRITICAL_STEPS for s in steps
    )

    if has_critical:
        status = "failed"
    elif has_non_critical:
        status = "partial"
    else:
        status = "completed"

    # ADR 013: compute quality gating statistics
    gate_results: list[GatingResult] = ctx.get("gate_results", []) if ctx else []
    questions_passed = sum(1 for gr in gate_results if gr.gate == "pass")
    questions_warning = sum(1 for gr in gate_results if gr.gate == "warning")
    questions_failed = sum(1 for gr in gate_results if gr.gate == "failed")
    failed_question_ids = [gr.question_id for gr in gate_results if gr.gate == "failed"]
    quality_warning_counts: dict[str, int] = {}
    for gr in gate_results:
        for wc in gr.warning_codes:
            quality_warning_counts[wc] = quality_warning_counts.get(wc, 0) + 1

    # ADR 013: if all questions failed gating, mark paper as partial
    if gate_results and all(gr.gate == "failed" for gr in gate_results):
        if status == "completed":
            status = "partial"

    counts: dict = {}
    for s in steps:
        if s.output_count > 0:
            counts[s.name] = s.output_count
    counts["steps_total"] = len(steps)
    counts["steps_succeeded"] = sum(1 for s in steps if s.status == "success")
    counts["steps_warning"] = sum(1 for s in steps if s.status == "warning")
    counts["steps_failed"] = sum(1 for s in steps if s.status == "failed")
    counts["steps_skipped"] = sum(1 for s in steps if s.status == "skipped")

    report = IngestionReport(
        paper_id=paper_id,
        status=status,
        started_at=started_at,
        finished_at=_now_iso(),
        steps=steps,
        counts=counts,
        warnings=warnings,
        errors=errors,
        questions_passed=questions_passed,
        questions_warning=questions_warning,
        questions_failed=questions_failed,
        failed_question_ids=failed_question_ids,
        quality_warning_counts=quality_warning_counts,
    )

    report_path = work_path / "run-report.json"
    report_path.write_text(report.to_json() + "\n", encoding="utf-8")
    return report


def _discover_mineru_json_files(work_path: Path) -> list[Path]:
    content_list = sorted(work_path.rglob("*_content_list.json"))
    if content_list:
        return content_list

    middle = sorted(work_path.rglob("*_middle.json"))
    if middle:
        return middle

    return sorted(work_path.rglob("*.json"))


def _load_layout_elements(json_path: Path) -> list[dict[str, Any]]:
    raw = json.loads(json_path.read_text(encoding="utf-8"))

    if _looks_like_layout_elements(raw):
        return raw

    if _looks_like_mineru_content_list(raw):
        return _mineru_content_list_to_layout_elements(raw)

    if _looks_like_mineru_content_list_v2(raw):
        flattened: list[dict[str, Any]] = []
        for page_idx, page_items in enumerate(raw):
            for item in page_items:
                if isinstance(item, dict):
                    copied = dict(item)
                    copied.setdefault("page_idx", page_idx)
                    flattened.append(copied)
        return _mineru_content_list_to_layout_elements(flattened)

    raise ValueError(
        f"Unsupported MinerU JSON shape for layout ownership: {json_path.name}"
    )


def _looks_like_layout_elements(raw: Any) -> bool:
    if not isinstance(raw, list):
        return False
    if not raw:
        return True
    sample = [item for item in raw[:5] if isinstance(item, dict)]
    return bool(sample) and all(
        "page" in item and "type" in item and "bbox" in item for item in sample
    )


def _looks_like_mineru_content_list(raw: Any) -> bool:
    if not isinstance(raw, list):
        return False
    if not raw:
        return True
    sample = [item for item in raw[:5] if isinstance(item, dict)]
    return bool(sample) and all("page_idx" in item and "bbox" in item for item in sample)


def _looks_like_mineru_content_list_v2(raw: Any) -> bool:
    return isinstance(raw, list) and bool(raw) and all(
        isinstance(page_items, list) for page_items in raw[:5]
    )


def _mineru_content_list_to_layout_elements(
    raw_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []

    for idx, item in enumerate(raw_items, start=1):
        bbox = _normalize_mineru_bbox(item.get("bbox"))
        if bbox is None:
            continue

        page_idx = item.get("page_idx", 0)
        if not isinstance(page_idx, int) or page_idx < 0:
            page_idx = 0

        mineru_type = str(item.get("type", "text") or "text")
        element_type = _map_mineru_element_type(mineru_type)
        text = _mineru_item_text(item, mineru_type)

        elements.append({
            "id": f"m{idx:06d}",
            "page": page_idx + 1,
            "type": element_type,
            "bbox": bbox,
            "text": text,
            "confidence": float(item.get("confidence", 1.0) or 1.0),
        })

    return elements


def _normalize_mineru_bbox(raw_bbox: Any) -> list[float] | None:
    if not isinstance(raw_bbox, list | tuple) or len(raw_bbox) != 4:
        return None

    coords = [float(v) for v in raw_bbox]
    scale = 1000.0 if max(coords) > 1.0 else 1.0
    x1, y1, x2, y2 = [min(1.0, max(0.0, v / scale)) for v in coords]
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def _map_mineru_element_type(mineru_type: str) -> str:
    mapping = {
        "text": "text",
        "list": "text",
        "header": "header",
        "footer": "footer",
        "page_number": "footer",
        "equation": "formula",
        "interline_equation": "formula",
        "inline_equation": "formula",
        "image": "image",
        "table": "table",
        "chart": "figure",
    }
    return mapping.get(mineru_type, "text")


def _mineru_item_text(item: dict[str, Any], mineru_type: str) -> str:
    if mineru_type == "list":
        list_items = item.get("list_items")
        if isinstance(list_items, list):
            return "\n".join(str(x) for x in list_items)

    for key in ("text", "content", "table_body", "table_caption", "img_caption"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list):
            return "\n".join(str(x) for x in value if str(x).strip())

    return ""


# ---------------------------------------------------------------------------
# Step 1: MinerU parse
# ---------------------------------------------------------------------------


def _step_mineru_parse(
    paper_id: str,
    pdf_path: str,
    work_dir: str,
    resume: bool,
    mineru_command: str,
    ctx: dict,
) -> StepResult:
    started = _now_iso()
    work_path = Path(work_dir)

    # Require both markdown AND elements JSON artifacts to skip MinerU.
    # MinerU 3.x nests output in subdirectories (e.g. <pdf_name>/auto/),
    # so check by globbing rather than hardcoding flat paths.
    if resume:
        md_files = list(work_path.rglob("*.md"))
        json_files = _discover_mineru_json_files(work_path)
        if md_files and json_files:
            ctx["mineru_result"] = MinerUResult(
                output_dir=work_path,
                markdown_path=md_files[0],
                raw_json_path=json_files[0],
            )
            return _make_result("mineru_parse", "skipped", started)

    runner = LocalMinerURunner(command=mineru_command)
    result = runner.parse_pdf(Path(pdf_path), work_path)
    ctx["mineru_result"] = result
    ok = 1 if (result.markdown_path and result.markdown_path.exists()) else 0
    return _make_result("mineru_parse", "success", started,
                        input_count=1, output_count=ok)


# ---------------------------------------------------------------------------
# Step 2: Layout ownership
# ---------------------------------------------------------------------------


def _step_layout_ownership(
    paper_id: str,
    ctx: dict,
) -> StepResult:
    started = _now_iso()
    min_result: MinerUResult | None = ctx.get("mineru_result")
    if min_result is None or min_result.raw_json_path is None:
        raise FileNotFoundError("MinerU elements JSON not found — mineru_parse must run first")

    raw_elements = _load_layout_elements(min_result.raw_json_path)
    blocks = layout_ownership(paper_id, raw_elements)

    # Build elements_by_id for downstream steps
    elements_by_id: dict[str, _Element] = {}
    for elem in raw_elements:
        eid = elem.get("id", "")
        bbox = elem.get("bbox", [0, 0, 0, 0])
        elements_by_id[eid] = _Element(
            id=eid,
            page=elem.get("page", 1),
            type=elem.get("type", ""),
            bbox=tuple(bbox) if len(bbox) == 4 else (0.0, 0.0, 0.0, 0.0),
            text=elem.get("text", ""),
            confidence=elem.get("confidence", 0.0),
            width=elem.get("width", 0.0),
            height=elem.get("height", 0.0),
        )

    # Store in ctx for steps 3, 5, and 9
    ctx["layout_blocks"] = blocks
    ctx["elements_by_id"] = elements_by_id

    return _make_result("layout_ownership", "success", started,
                        input_count=len(raw_elements), output_count=len(blocks))


# ---------------------------------------------------------------------------
# Step 3: DeepSeek structure — uses layout_ownership blocks from ctx
# ---------------------------------------------------------------------------


def _step_deepseek_structure(
    paper_id: str,
    deepseek_client,
    ctx: dict,
) -> StepResult:
    started = _now_iso()

    blocks: list[LayoutOwnershipBlock] = ctx.get("layout_blocks", [])
    elements_by_id: dict[str, _Element] = ctx.get("elements_by_id", {})

    if not blocks:
        raise RuntimeError("No layout blocks in context — layout_ownership must run first")

    # Read markdown for answer section parsing (from MinerUResult in ctx)
    min_result: MinerUResult | None = ctx.get("mineru_result")
    markdown = ""
    if min_result and min_result.markdown_path and min_result.markdown_path.exists():
        markdown = min_result.markdown_path.read_text(encoding="utf-8").strip()

    answer_entries = parse_answer_entries(markdown)

    question_blocks: list[QuestionBlock] = []
    questions: list[Question] = []
    reports: list[QualityReport] = []
    gate_results: list[GatingResult] = []

    for index, lb in enumerate(blocks, start=1):
        # Build QuestionBlock from LayoutOwnershipBlock
        qb = _layout_block_to_question_block(lb, paper_id, elements_by_id)
        question_blocks.append(qb)

        # DeepSeek structuring using element text (not raw markdown splitter)
        payload = deepseek_client.structure_question(qb.raw_markdown)
        question = _question_from_payload(paper_id, index, payload)

        if not question.choices:
            question.choices = parse_choices(qb.raw_markdown)

        if lb.question_number in answer_entries:
            parsed_answer = parse_answer_entry(answer_entries[lb.question_number])
            if not question.answer_latex and parsed_answer.answer_latex:
                question.answer_latex = parsed_answer.answer_latex
            if not question.analysis_latex and parsed_answer.analysis_latex:
                question.analysis_latex = parsed_answer.analysis_latex

        question.question_type = infer_question_type(question, qb)
        questions.append(question)

        report = validate_question(question)
        report.model_warnings = [
            str(w) for w in payload.get("warnings", []) if str(w).strip()
        ]
        if report.model_warnings:
            report.needs_review = True
        reports.append(report)

        # ADR 013: quality gating
        gate_result = gate_question(question, qb)
        gate_results.append(gate_result)

    # Build full ProcessingResult (all questions, for reporting)
    result = ProcessingResult(
        paper_id=paper_id,
        blocks=question_blocks,
        questions=questions,
        quality_reports=reports,
    )
    ctx["processing_result"] = result
    ctx["gate_results"] = gate_results
    ctx["markdown"] = markdown

    return _make_result("deepseek_structure", "success", started,
                        input_count=len(blocks), output_count=len(questions))


def _question_from_payload(paper_id: str, index: int, payload: dict) -> Question:
    """Build a Question from a DeepSeek payload (reuses ProcessingPipeline logic)."""
    choices = [
        Choice(
            label=str(c.get("label", "")).strip(),
            content_latex=str(c.get("content_latex", "")).strip(),
            sort_order=pos,
        )
        for pos, c in enumerate(payload.get("choices", []), start=1)
        if isinstance(c, dict)
    ]
    return Question(
        id=f"{paper_id}_q_{index:04d}",
        question_type=str(payload.get("question_type", "unknown")),
        stem_latex=str(payload.get("stem_latex", "")).strip(),
        choices=choices,
        answer_latex=str(payload.get("answer_latex", "")).strip(),
        analysis_latex=str(payload.get("analysis_latex", "")).strip(),
        knowledge_points=list(payload.get("knowledge_points", [])),
        difficulty=payload.get("difficulty"),
    )


# ---------------------------------------------------------------------------
# Step 4: Save questions/blocks
# ---------------------------------------------------------------------------


def _step_save_questions(
    paper_id: str,
    repository,
    dry_run: bool,
    ctx: dict,
) -> StepResult:
    started = _now_iso()

    result: ProcessingResult | None = ctx.get("processing_result")
    gate_results: list[GatingResult] = ctx.get("gate_results", [])

    if result is None:
        if dry_run:
            return _make_result("save_questions", "skipped", started, output_count=0)
        raise RuntimeError("No ProcessingResult in context — deepseek_structure must run first")

    # ADR 013: filter out failed questions before saving
    failed_ids = {gr.question_id for gr in gate_results if gr.gate == "failed"}
    if failed_ids:
        gated_blocks = [
            b for b, q in zip(result.blocks, result.questions)
            if q.id not in failed_ids
        ]
        gated_questions = [q for q in result.questions if q.id not in failed_ids]
        gated_reports = [r for r in result.quality_reports if r.question_id not in failed_ids]
        save_result = ProcessingResult(
            paper_id=result.paper_id,
            blocks=gated_blocks,
            questions=gated_questions,
            quality_reports=gated_reports,
        )
    else:
        save_result = result

    ctx["save_result"] = save_result
    layout_blocks: list[LayoutOwnershipBlock] = ctx.get("layout_blocks", [])
    ctx["gated_layout_blocks"] = [
        lb for lb, q in zip(layout_blocks, result.questions)
        if q.id not in failed_ids
    ] if layout_blocks else []

    if dry_run:
        return _make_result("save_questions", "skipped", started,
                            output_count=len(save_result.questions))

    repository.save_processing_result(save_result)
    return _make_result("save_questions", "success", started,
                        input_count=len(save_result.blocks),
                        output_count=len(save_result.questions))


# ---------------------------------------------------------------------------
# Step 5: Identify raw assets — reuses layout blocks from ctx
# ---------------------------------------------------------------------------


def _step_identify_assets(
    paper_id: str,
    repository,
    dry_run: bool,
    resume: bool,
    ctx: dict,
) -> StepResult:
    started = _now_iso()

    if dry_run:
        return _make_result("identify_assets", "skipped", started)

    # Resume: skip if raw_assets already exist for this paper
    if resume and repository is not None:
        try:
            existing = repository.list_raw_assets(paper_id=paper_id, limit=1)
            if existing:
                return _make_result("identify_assets", "skipped", started,
                                    output_count=len(existing))
        except Exception:
            pass

    # Reuse saved/gated layout blocks from step 4 instead of recomputing.
    # Failed-gated questions are not persisted, so downstream asset links must
    # not point at their question_block_id values either.
    blocks: list[LayoutOwnershipBlock] | None = ctx.get("gated_layout_blocks")
    if blocks is None:
        blocks = ctx.get("layout_blocks", [])
    elements_by_id: dict[str, _Element] = ctx.get("elements_by_id", {})

    if not blocks:
        if "gated_layout_blocks" in ctx:
            return _make_result("identify_assets", "success", started,
                                input_count=0, output_count=0)
        raise RuntimeError("No layout blocks in context — layout_ownership must run first")

    result = repository.identify_paper_assets(paper_id, blocks, elements_by_id)

    return _make_result("identify_assets", "success", started,
                        input_count=len(blocks),
                        output_count=len(result["raw_assets"]))


# ---------------------------------------------------------------------------
# Step 6: Crop assets (non-critical)
# ---------------------------------------------------------------------------


def _step_crop_assets(
    paper_id: str,
    pdf_path: str,
    asset_dir: str,
    repository,
    dry_run: bool,
) -> StepResult:
    started = _now_iso()

    if dry_run:
        return _make_result("crop_assets", "skipped", started)

    raw_assets = repository.list_raw_assets(paper_id=paper_id, limit=10000)
    if not raw_assets:
        return _make_result("crop_assets", "success", started,
                            input_count=0, output_count=0)

    to_crop = [ra for ra in raw_assets if not ra.get("crop_path")]
    if not to_crop:
        return _make_result("crop_assets", "skipped", started,
                            input_count=len(raw_assets),
                            output_count=len(raw_assets))

    try:
        results = crop_pdf_assets(pdf_path, to_crop, asset_dir)
    except (ImportError, FileNotFoundError) as exc:
        return _make_result("crop_assets", "failed", started,
                            error=str(exc), input_count=len(to_crop))

    success = 0
    failed = 0
    warn_msgs: list[str] = []

    for r in results:
        if r.error is not None:
            repository.update_raw_asset_crop(
                raw_asset_id=r.raw_asset_id, crop_path=None,
                storage_url=None, content_hash="", width=None,
                height=None, status="crop_failed",
            )
            failed += 1
            warn_msgs.append(f"{r.raw_asset_id}: {r.error}")
        else:
            stored = store_crop_result(r, asset_dir, paper_id)
            repository.update_raw_asset_crop(
                raw_asset_id=r.raw_asset_id,
                crop_path=stored.file_path,
                storage_url=stored.storage_url,
                content_hash=r.content_hash,
                width=stored.width,
                height=stored.height,
                status="active",
            )
            success += 1

    repository.connection.commit()

    return _make_result(
        "crop_assets",
        "warning" if failed > 0 else "success",
        started,
        input_count=len(to_crop),
        output_count=success,
        warnings=warn_msgs,
    )


# ---------------------------------------------------------------------------
# Step 7: Store assets (non-critical)
# ---------------------------------------------------------------------------


def _step_store_assets(
    paper_id: str,
    asset_dir: str,
    repository,
    dry_run: bool,
) -> StepResult:
    started = _now_iso()

    if dry_run:
        return _make_result("store_assets", "skipped", started)

    raw_assets = repository.list_raw_assets(paper_id=paper_id, limit=10000)
    stored = sum(1 for ra in raw_assets if ra.get("storage_url"))
    return _make_result("store_assets", "success", started,
                        input_count=len(raw_assets), output_count=stored)


# ---------------------------------------------------------------------------
# Step 8: Compute pHash (non-critical)
# ---------------------------------------------------------------------------


def _step_compute_phash(
    paper_id: str,
    repository,
    dry_run: bool,
) -> StepResult:
    started = _now_iso()

    if dry_run:
        return _make_result("compute_phash", "skipped", started)

    raw_assets = repository.list_raw_assets(paper_id=paper_id, limit=10000)
    ok = 0
    skip = 0
    fail = 0
    warn_msgs: list[str] = []

    for ra in raw_assets:
        crop_path = ra.get("crop_path")
        if not crop_path:
            skip += 1
            continue
        if ra.get("perceptual_hash", ""):
            ok += 1
            continue

        try:
            ph = compute_phash(crop_path)
        except Exception as exc:
            fail += 1
            warn_msgs.append(f"{ra['id']}: {exc}")
            continue

        repository.update_raw_asset_phash(ra["id"], ph)
        ok += 1

    repository.connection.commit()

    return _make_result(
        "compute_phash",
        "warning" if fail > 0 else "success",
        started,
        input_count=len(raw_assets),
        output_count=ok,
        warnings=warn_msgs,
    )


# ---------------------------------------------------------------------------
# Step 9: Duplicate candidates (non-critical, cross-paper)
# ---------------------------------------------------------------------------


def _step_duplicate_candidates(
    paper_id: str,
    repository,
    dry_run: bool,
    ctx: dict,
) -> StepResult:
    started = _now_iso()

    if dry_run or repository is None:
        return _make_result("duplicate_candidates", "skipped", started)

    try:
        identities_by_paper: dict[str, list[QuestionIdentity]] = {}

        # Current paper: use proper fingerprint_blocks() from ADR 003
        layout_blocks: list[LayoutOwnershipBlock] | None = ctx.get("gated_layout_blocks")
        if layout_blocks is None:
            layout_blocks = ctx.get("layout_blocks", [])
        elements_by_id: dict[str, _Element] = ctx.get("elements_by_id", {})
        if layout_blocks:
            identities_by_paper[paper_id] = fingerprint_blocks(
                paper_id, layout_blocks, elements_by_id,
            )

        # Other papers: query DB and use simplified fingerprints (v1 limitation)
        cursor = repository.connection.cursor()
        cursor.execute(
            """SELECT id, paper_id, question_number, section_title, raw_markdown
               FROM question_blocks WHERE paper_id != %(paper_id)s
               ORDER BY paper_id, question_number""",
            {"paper_id": paper_id},
        )
        rows = cursor.fetchall()

        for row in rows:
            if isinstance(row, dict):
                bid, pid, qn, sect, md = (
                    row["id"], row["paper_id"], row["question_number"],
                    row.get("section_title", ""), row.get("raw_markdown", ""),
                )
            else:
                bid, pid, qn, sect, md = row[0], row[1], row[2], row[3] or "", row[4] or ""

            identities_by_paper.setdefault(pid, []).append(QuestionIdentity(
                block_id=bid,
                source_position_key=f"{pid}#{sect}#{qn}",
                text_fingerprint=_text_fp(md),
                latex_fingerprint=_latex_fp(md),
                asset_signature="",
            ))

        if not identities_by_paper:
            return _make_result("duplicate_candidates", "success", started,
                                input_count=0, output_count=0)

        groups = generate_candidate_groups(
            identities_by_paper, fingerprint_type="text", min_candidates=2,
        )

        saved = 0
        save_errors: list[str] = []
        for g in groups:
            try:
                repository.save_duplicate_candidate_group(g)
                saved += 1
            except Exception as exc:
                save_errors.append(f"{g.id}: {exc}")

        if saved > 0:
            repository.connection.commit()

        total_row_count = len(identities_by_paper.get(paper_id, []))
        for pid, idents in identities_by_paper.items():
            if pid != paper_id:
                total_row_count += len(idents)

        return _make_result(
            "duplicate_candidates",
            "warning" if save_errors else "success",
            started,
            input_count=total_row_count,
            output_count=saved,
            warnings=save_errors,
        )
    except Exception as exc:
        return _make_result("duplicate_candidates", "warning", started, error=str(exc))


# ---------------------------------------------------------------------------
# Step 10: Visual candidates (non-critical, cross-paper)
# ---------------------------------------------------------------------------


def _step_visual_candidates(repository) -> StepResult:
    started = _now_iso()

    if repository is None:
        return _make_result("visual_candidates", "skipped", started)

    try:
        raw_assets = repository.list_raw_assets(limit=10000)
        candidates = generate_visual_asset_candidates(raw_assets, max_distance=8)
        return _make_result("visual_candidates", "success", started,
                            input_count=len(raw_assets),
                            output_count=len(candidates))
    except Exception as exc:
        return _make_result("visual_candidates", "warning", started, error=str(exc))


# ---------------------------------------------------------------------------
# Simplified fingerprint helpers (for cross-paper DB queries where elements
# are not available — v1 limitation documented in ADR 009).
# ---------------------------------------------------------------------------


def _text_fp(raw_markdown: str) -> str:
    import hashlib
    import re
    if not raw_markdown:
        return ""
    text = re.sub(r"\s+", "", raw_markdown)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""


def _latex_fp(raw_markdown: str) -> str:
    import hashlib
    import re
    if not raw_markdown:
        return ""
    formulas = re.findall(r"\$(.+?)\$", raw_markdown)
    if not formulas:
        return ""
    formulas.sort()
    return hashlib.sha256(" | ".join(formulas).encode("utf-8")).hexdigest()[:16]
