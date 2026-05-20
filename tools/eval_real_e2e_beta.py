"""ADR 020/021: Small-Scale Real Ingestion Beta evaluation tool.

Validates the full ingestion path with real DeepSeek, non-dry-run PostgreSQL
writes, asset linkage, crop/pHash pipeline, and duplicate/visual candidates
across 20 PDFs.

Usage:
  python3 tools/eval_real_e2e_beta.py --pdf-dir data/beta/pdf --limit 20
  python3 tools/eval_real_e2e_beta.py --pdf-dir data/beta/pdf --limit 20 --resume
  python3 tools/eval_real_e2e_beta.py --pdf-dir data/beta/pdf --only-index 12 --resume
  python3 tools/eval_real_e2e_beta.py --summarize-existing --work-root data/runs/real_beta_2026-05-19
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.eval_deepseek_structure import count_pages


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


class _ADR021ArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args, namespace)
        if not parsed.summarize_existing and not parsed.pdf_dir:
            self.error("--pdf-dir is required unless --summarize-existing is used")
        return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = _ADR021ArgumentParser(
        description="Real E2E ingestion beta evaluation (ADR 020/021)"
    )
    parser.add_argument(
        "--pdf-dir", type=Path,
        help="Directory containing PDF files to process (required unless --summarize-existing)")
    parser.add_argument(
        "--limit", type=int, default=20,
        help="Max number of PDFs to process (default: 20)")
    parser.add_argument(
        "--paper-prefix", type=str, default="real_beta_2026_05_19",
        help="Prefix for paper IDs (default: real_beta_2026_05_19)")
    parser.add_argument(
        "--work-root", type=Path, default=None,
        help="Root for per-paper work dirs (default: data/runs/real_beta_<date>)")
    parser.add_argument(
        "--asset-dir", type=Path, default=Path("data/assets"),
        help="Asset storage directory (default: data/assets)")
    parser.add_argument(
        "--resume", action="store_true",
        help="Pass --resume to each paper's ingest-full invocation")
    parser.add_argument(
        "--report-dir", type=Path, default=Path("docs/eval"),
        help="Output directory for eval report (default: docs/eval)")
    # ADR 021: summarise existing run reports without re-ingesting
    parser.add_argument(
        "--summarize-existing", action="store_true",
        help="Recompute md+json summary from existing run-report.json files "
             "(no re-ingestion, requires DB for asset link queries)")
    # ADR 021: single-PDF re-run
    parser.add_argument(
        "--only-index", type=int, default=None,
        help="Process only the Nth PDF (1-indexed) — for single-paper re-runs")
    parser.add_argument(
        "--only-paper", type=str, default=None,
        help="Process only the PDF matching this paper ID prefix or name")
    return parser


# ---------------------------------------------------------------------------
# Per-paper processing
# ---------------------------------------------------------------------------


def _process_one_pdf(
    pdf_path: Path,
    index: int,
    prefix: str,
    work_root: Path,
    asset_dir: Path,
    resume: bool,
    deepseek_client,
    mineru_command: str,
    repository,
) -> dict[str, Any]:
    """Run ingest_paper_full on a single PDF and extract full stats."""
    paper_id = f"{prefix}_{index:04d}"
    work_dir = work_root / paper_id
    started = time.monotonic()

    from question_bank.services.paper_orchestrator import ingest_paper_full

    report = ingest_paper_full(
        paper_id=paper_id,
        pdf_path=str(pdf_path),
        work_dir=str(work_dir),
        asset_dir=str(asset_dir),
        dry_run=False,
        resume=resume,
        repository=repository,
        deepseek_client=deepseek_client,
        mineru_command=mineru_command,
    )

    elapsed = time.monotonic() - started

    # Extract step-level data
    step_data: dict[str, dict] = {}
    for s in report.steps:
        step_data[s.name] = {
            "status": s.status,
            "output_count": s.output_count,
            "warnings": s.warnings,
        }

    layout_q = step_data.get("layout_ownership", {}).get("output_count", 0)
    deepseek_out = step_data.get("deepseek_structure", {}).get("output_count", 0)

    # Asset pipeline metrics from step data
    raw_assets = step_data.get("identify_assets", {}).get("output_count", 0)
    crop_success = step_data.get("crop_assets", {}).get("output_count", 0)
    crop_warnings = step_data.get("crop_assets", {}).get("warnings", [])
    crop_failed = len(crop_warnings)
    phash_success = step_data.get("compute_phash", {}).get("output_count", 0)
    duplicate_candidates = step_data.get("duplicate_candidates", {}).get("output_count", 0)
    visual_candidates = step_data.get("visual_candidates", {}).get("output_count", 0)

    # Question asset links and integrity checks — query DB directly
    qa_links = 0
    unlinked_raw_assets = 0
    links_without_question_block = 0
    if repository is not None and report.status != "failed":
        try:
            cursor = repository.connection.cursor()
            cursor.execute(
                """SELECT COUNT(*)
                   FROM question_asset_links qal
                   JOIN raw_assets ra ON ra.id = qal.raw_asset_id
                   WHERE ra.paper_id = %(paper_id)s""",
                {"paper_id": paper_id},
            )
            row = cursor.fetchone()
            qa_links = (row[0] if isinstance(row, tuple) else row["count"]) if row else 0

            cursor.execute(
                """SELECT COUNT(*)
                   FROM raw_assets ra
                   WHERE ra.paper_id = %(paper_id)s
                     AND NOT EXISTS (
                         SELECT 1 FROM question_asset_links qal
                         WHERE qal.raw_asset_id = ra.id
                     )""",
                {"paper_id": paper_id},
            )
            row = cursor.fetchone()
            unlinked_raw_assets = (row[0] if isinstance(row, tuple) else row["count"]) if row else 0

            cursor.execute(
                """SELECT COUNT(*)
                   FROM question_asset_links qal
                   JOIN raw_assets ra ON ra.id = qal.raw_asset_id
                   LEFT JOIN question_blocks qb ON qb.id = qal.question_id
                   WHERE ra.paper_id = %(paper_id)s AND qb.id IS NULL""",
                {"paper_id": paper_id},
            )
            row = cursor.fetchone()
            links_without_question_block = (row[0] if isinstance(row, tuple) else row["count"]) if row else 0
        except Exception:
            qa_links = -1
            unlinked_raw_assets = -1
            links_without_question_block = -1

    # Page count from PDF
    pages = count_pages(pdf_path)

    # Error summary
    error = _report_error_summary(report) if report.status == "failed" else None

    return {
        "paper_id": paper_id,
        "pdf_path": str(pdf_path),
        "work_dir": str(work_dir),
        "status": report.status,
        "pages": pages,
        "layout_q": layout_q,
        "deepseek_out": deepseek_out,
        "questions_passed": report.questions_passed,
        "questions_warning": report.questions_warning,
        "questions_failed": report.questions_failed,
        "failed_question_ids": report.failed_question_ids,
        "quality_warning_counts": report.quality_warning_counts,
        "raw_assets": raw_assets,
        "qa_links": qa_links,
        "unlinked_raw_assets": unlinked_raw_assets,
        "links_without_question_block": links_without_question_block,
        "crop_success": crop_success,
        "crop_failed": crop_failed,
        "phash_success": phash_success,
        "duplicate_candidates": duplicate_candidates,
        "visual_candidates": visual_candidates,
        "elapsed_s": round(elapsed, 1),
        "retry_count": 0,
        "previous_error": None,
        "error": error,
    }


def _report_error_summary(report) -> str | None:
    """Extract a compact failure summary from an IngestionReport."""
    errors = getattr(report, "errors", None) or []
    if errors:
        return "; ".join(str(e) for e in errors if str(e).strip()) or None

    failed_steps: list[str] = []
    for step in getattr(report, "steps", []):
        if getattr(step, "status", "") == "failed":
            name = getattr(step, "name", "unknown")
            error = getattr(step, "error", None)
            failed_steps.append(f"{name}: {error}" if error else name)

    if failed_steps:
        return "; ".join(failed_steps)
    return None


def _process_one_safe(
    pdf_path: Path,
    index: int,
    prefix: str,
    work_root: Path,
    asset_dir: Path,
    resume: bool,
    deepseek_client,
    mineru_command: str,
    repository,
) -> dict[str, Any]:
    """Wrap _process_one_pdf with failure isolation and ADR 021 retry tracking."""
    paper_id = f"{prefix}_{index:04d}"
    work_dir = work_root / paper_id
    previous_error = None

    # ADR 021: preserve previous run-report.json if it exists (retry tracking)
    previous_report_path = work_dir / "run-report.json"
    if previous_report_path.exists():
        try:
            prev_data = json.loads(previous_report_path.read_text(encoding="utf-8"))
            prev_status = prev_data.get("status", "unknown")
            if prev_status == "failed":
                prev_errors = prev_data.get("errors", [])
                previous_error = "; ".join(prev_errors[:3]) if prev_errors else "previous run failed"
            previous_report_path.rename(work_dir / "run-report.previous.json")
        except Exception:
            pass

    try:
        result = _process_one_pdf(
            pdf_path, index, prefix, work_root, asset_dir,
            resume, deepseek_client, mineru_command, repository,
        )
        if previous_error:
            result["retry_count"] = result.get("retry_count", 0) + 1
            result["previous_error"] = previous_error[:200]
        return result
    except Exception as exc:
        return {
            "paper_id": paper_id,
            "pdf_path": str(pdf_path),
            "work_dir": str(work_dir),
            "status": "failed",
            "pages": None,
            "layout_q": 0,
            "deepseek_out": 0,
            "questions_passed": 0,
            "questions_warning": 0,
            "questions_failed": 0,
            "failed_question_ids": [],
            "quality_warning_counts": {},
            "raw_assets": 0,
            "qa_links": 0,
            "unlinked_raw_assets": 0,
            "links_without_question_block": 0,
            "crop_success": 0,
            "crop_failed": 0,
            "phash_success": 0,
            "duplicate_candidates": 0,
            "visual_candidates": 0,
            "elapsed_s": 0,
            "retry_count": 0,
            "previous_error": previous_error[:200] if previous_error else None,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _generate_markdown_report(results: list[dict], elapsed: float) -> str:
    """Generate ADR 020 evaluation markdown report."""
    today = datetime.now().strftime("%Y-%m-%d")
    total = len(results)

    total_passed = sum(r["questions_passed"] for r in results)
    total_warning = sum(r["questions_warning"] for r in results)
    total_failed = sum(r["questions_failed"] for r in results)
    total_questions = total_passed + total_warning + total_failed

    pipeline_completed = sum(1 for r in results if r["status"] == "completed")
    pipeline_partial = sum(1 for r in results if r["status"] == "partial")
    pipeline_failed = sum(1 for r in results if r["status"] == "failed")

    # Aggregate warning codes
    warning_counter: Counter[str] = Counter()
    for r in results:
        for code, count in r["quality_warning_counts"].items():
            warning_counter[code] += count

    # Asset metrics
    total_raw_assets = sum(r["raw_assets"] for r in results)
    total_qa_links = sum(r["qa_links"] for r in results if r["qa_links"] > 0)
    total_unlinked = sum(r["unlinked_raw_assets"] for r in results if r["unlinked_raw_assets"] > 0)
    total_broken_links = sum(
        r["links_without_question_block"] for r in results
        if r["links_without_question_block"] > 0
    )
    total_crop_success = sum(r["crop_success"] for r in results)
    total_crop_failed = sum(r["crop_failed"] for r in results)
    total_crop_attempts = total_crop_success + total_crop_failed
    total_phash = sum(r["phash_success"] for r in results)
    total_dup_candidates = sum(r["duplicate_candidates"] for r in results)
    total_vis_candidates = sum(r["visual_candidates"] for r in results)
    pdfs_with_assets = sum(1 for r in results if r["raw_assets"] > 0)

    lines: list[str] = []
    lines.append(f"# Real E2E Ingestion Beta — {today}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("This run validates full-batch real ingestion: 20 PDFs, real DeepSeek,")
    lines.append("non-dry-run PostgreSQL writes, with complete asset pipeline (crop,")
    lines.append("pHash, duplicate candidates, visual candidates).")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total PDFs | {total} |")
    lines.append(f"| Pipeline completed | {pipeline_completed} |")
    lines.append(f"| Pipeline partial | {pipeline_partial} |")
    lines.append(f"| Pipeline failed | {pipeline_failed} |")
    if total > 0:
        success_rate = (pipeline_completed + pipeline_partial) / total * 100
        lines.append(f"| Success rate (completed + partial) | {success_rate:.1f}% |")
    lines.append(f"| Total structured questions | {total_questions} |")
    lines.append(f"| Questions passed | {total_passed} |")
    lines.append(f"| Questions warning | {total_warning} |")
    lines.append(f"| Questions failed | {total_failed} |")
    if total_questions > 0:
        lines.append(f"| Pass rate | {total_passed / total_questions * 100:.1f}% |")
        lines.append(f"| Warning rate | {total_warning / total_questions * 100:.1f}% |")
    lines.append(f"| Total elapsed | {elapsed:.0f}s |")
    if total > 0:
        lines.append(f"| Avg per PDF | {elapsed / total:.1f}s |")
    lines.append("")

    # Asset summary
    lines.append("## Asset Pipeline Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| PDFs with raw_assets | {pdfs_with_assets} of {total} |")
    lines.append(f"| Total raw_assets | {total_raw_assets} |")
    lines.append(f"| Total question_asset_links | {total_qa_links} |")
    lines.append(f"| Unlinked raw_assets | {total_unlinked} |")
    lines.append(f"| Links without question_block | {total_broken_links} |")
    lines.append(f"| Crop successes | {total_crop_success} |")
    lines.append(f"| Crop failures | {total_crop_failed} |")
    if total_crop_attempts > 0:
        lines.append(f"| Crop success rate | {total_crop_success / total_crop_attempts * 100:.1f}% |")
    lines.append(f"| pHash computed | {total_phash} |")
    if total_crop_success + total_crop_failed > 0:
        total_phashable = total_crop_success  # only cropped can get pHash
        if total_phashable > 0:
            lines.append(f"| pHash success rate | {total_phash / total_phashable * 100:.1f}% |")
    lines.append(f"| Duplicate candidate groups | {total_dup_candidates} |")
    lines.append(f"| Visual candidate groups | {total_vis_candidates} |")
    lines.append("")

    # Per-paper results table
    lines.append("## Per-Paper Results")
    lines.append("")
    has_retries = any(r.get("retry_count", 0) > 0 for r in results)
    header = "| Paper ID | Pg | Layout | Struct | Pass | Warn | Fail | "
    if has_retries:
        header += "Rtry | "
    header += "Assets | Links | CropOK | CropFail | pHash | Dup | Vis | Status |"
    sep = "|----------|----|--------|--------|------|------|------|"
    if has_retries:
        sep += "----|"
    sep += "--------|-------|--------|----------|-------|-----|-----|--------|"
    lines.append(header)
    lines.append(sep)
    for r in results:
        pg = str(r["pages"] or "?")
        row = (f"| {r['paper_id']} | {pg} | {r['layout_q']} | {r['deepseek_out']} | "
               f"{r['questions_passed']} | {r['questions_warning']} | {r['questions_failed']} | ")
        if has_retries:
            row += f"{r.get('retry_count', 0)} | "
        row += (f"{r['raw_assets']} | {r['qa_links']} | {r['crop_success']} | {r['crop_failed']} | "
                f"{r['phash_success']} | {r['duplicate_candidates']} | {r['visual_candidates']} | "
                f"{r['status']} |")
        lines.append(row)
    lines.append("")

    # Quality warning distribution
    if warning_counter:
        lines.append("## Quality Warning Distribution")
        lines.append("")
        lines.append("| Warning Code | Count |")
        lines.append("|--------------|-------|")
        for code, count in warning_counter.most_common():
            lines.append(f"| {code} | {count} |")
        lines.append("")

    # Failed question details
    all_failed_ids: list[tuple[str, str]] = []
    for r in results:
        for qid in r["failed_question_ids"]:
            all_failed_ids.append((r["paper_id"], qid))
    if all_failed_ids:
        lines.append("## Failed Questions")
        lines.append("")
        lines.append("| Paper ID | Question ID |")
        lines.append("|----------|-------------|")
        for paper_id, qid in all_failed_ids:
            lines.append(f"| {paper_id} | {qid} |")
        lines.append("")

    # Pipeline errors
    pipeline_errors = [r for r in results if r["error"]]
    if pipeline_errors:
        lines.append("## Pipeline Errors")
        lines.append("")
        lines.append("| Paper ID | Error |")
        lines.append("|----------|-------|")
        for r in pipeline_errors:
            lines.append(f"| {r['paper_id']} | {r['error'][:200]} |")
        lines.append("")

    # Retry history (ADR 021)
    retried = [r for r in results if r.get("retry_count", 0) > 0]
    if retried:
        lines.append("## Retry History")
        lines.append("")
        lines.append("| Paper ID | Final Status | Reruns | Previous Error |")
        lines.append("|----------|-------------|--------|----------------|")
        for r in retried:
            prev = (r.get("previous_error") or "unknown")[:120]
            lines.append(f"| {r['paper_id']} | {r['status']} | {r.get('retry_count', 0)} | {prev} |")
        lines.append("")

    # Conclusion
    lines.append("## Conclusion")
    lines.append("")
    _append_conclusion(lines, results, total, total_passed, total_warning, total_failed,
                       total_questions, pipeline_completed, pipeline_partial,
                       pipeline_failed, warning_counter,
                       total_raw_assets, total_qa_links, total_unlinked,
                       total_broken_links, total_crop_success,
                       total_crop_failed, total_phash, pdfs_with_assets)

    return "\n".join(lines) + "\n"


def _append_conclusion(
    lines: list[str],
    results: list[dict],
    total: int,
    total_passed: int,
    total_warning: int,
    total_failed: int,
    total_questions: int,
    pipeline_completed: int,
    pipeline_partial: int,
    pipeline_failed: int,
    warning_counter: Counter[str],
    total_raw_assets: int,
    total_qa_links: int,
    total_unlinked: int,
    total_broken_links: int,
    total_crop_success: int,
    total_crop_failed: int,
    total_phash: int,
    pdfs_with_assets: int,
) -> None:
    """Compute and append ADR 020 verdict with acceptance gate checks."""

    # Gate 1: completed + partial >= 90%
    success_total = pipeline_completed + pipeline_partial
    gate_success = success_total >= total * 0.9

    # Gate 2: pipeline failed = 0
    gate_no_failures = pipeline_failed == 0

    # Gate 3: questions_failed = 0
    gate_no_failed_questions = total_failed == 0

    # Gate 4: warning rate <= 10%
    warning_ratio = total_warning / total_questions if total_questions > 0 else 0
    gate_warning = warning_ratio <= 0.1

    # Gate 5: raw_assets > 0 on ≥ 50% PDFs
    gate_assets = pdfs_with_assets >= total * 0.5

    # Gate 6: crop success rate >= 80%
    gate_links = total_qa_links > 0

    # Gate 7: unlinked raw_assets <= 10%
    unlinked_rate = total_unlinked / total_raw_assets if total_raw_assets > 0 else 0
    gate_unlinked = unlinked_rate <= 0.1

    # Gate 8: question_asset_links point to existing question_blocks
    gate_link_integrity = total_broken_links == 0

    # Gate 9: crop success rate >= 80%
    total_crop_attempts = total_crop_success + total_crop_failed
    crop_rate = total_crop_success / total_crop_attempts if total_crop_attempts > 0 else 1.0
    gate_crop = crop_rate >= 0.8

    # Gate 10: pHash success rate >= 80%
    phash_rate = total_phash / total_crop_success if total_crop_success > 0 else 1.0
    gate_phash = phash_rate >= 0.8

    all_gates_passed = all([
        gate_success, gate_no_failures, gate_no_failed_questions,
        gate_warning, gate_assets, gate_links, gate_unlinked,
        gate_link_integrity, gate_crop, gate_phash,
    ])

    lines.append("### Acceptance Gates")
    lines.append("")
    lines.append("| Gate | Threshold | Actual | Status |")
    lines.append("|------|-----------|--------|--------|")
    _gate_row(lines, "Completed + partial ≥ 90%", f"≥ {total * 0.9:.0f}",
              f"{success_total} of {total} ({success_total / total * 100:.1f}%)", gate_success)
    _gate_row(lines, "Pipeline failed = 0", "0", str(pipeline_failed), gate_no_failures)
    _gate_row(lines, "Questions failed = 0", "0", str(total_failed), gate_no_failed_questions)
    _gate_row(lines, "Warning rate ≤ 10%", "≤ 10%",
              f"{warning_ratio:.1%}", gate_warning)
    _gate_row(lines, "raw_assets > 0 on ≥ 50% PDFs", "≥ 50%",
              f"{pdfs_with_assets} of {total} ({pdfs_with_assets / total * 100:.1f}%)", gate_assets)
    _gate_row(lines, "question_asset_links > 0", "> 0", str(total_qa_links), gate_links)
    _gate_row(lines, "Unlinked raw_assets ≤ 10%", "≤ 10%",
              f"{unlinked_rate:.1%}", gate_unlinked)
    _gate_row(lines, "Links without question_block = 0", "0", str(total_broken_links), gate_link_integrity)
    _gate_row(lines, "Crop success ≥ 80%", "≥ 80%",
              f"{crop_rate:.1%}" if total_crop_attempts > 0 else "N/A", gate_crop)
    _gate_row(lines, "pHash success ≥ 80%", "≥ 80%",
              f"{phash_rate:.1%}" if total_crop_success > 0 else "N/A", gate_phash)
    lines.append("")

    if all_gates_passed:
        lines.append("**PASS** — All acceptance gates passed. "
                     "Ready for full-scale production ingestion.")
    else:
        lines.append("**BLOCKED** — One or more acceptance gates failed.")
        lines.append("")
        failed_gates: list[str] = []
        if not gate_success:
            failed_gates.append(f"- Success rate {success_total / total * 100:.1f}% below 90% threshold")
        if not gate_no_failures:
            failed_gates.append(f"- {pipeline_failed} pipeline failure(s)")
        if not gate_no_failed_questions:
            failed_gates.append(f"- {total_failed} question(s) failed quality gating")
        if not gate_warning:
            failed_gates.append(f"- Warning rate {warning_ratio:.1%} above 10% threshold")
        if not gate_assets:
            failed_gates.append(f"- Only {pdfs_with_assets}/{total} PDFs have raw_assets (threshold: 50%)")
        if not gate_links:
            failed_gates.append("- No question_asset_links were generated")
        if not gate_unlinked:
            failed_gates.append(f"- Unlinked raw_assets rate {unlinked_rate:.1%} above 10%")
        if not gate_link_integrity:
            failed_gates.append(f"- {total_broken_links} question_asset_links do not point to a question_block")
        if not gate_crop:
            failed_gates.append(f"- Crop success rate {crop_rate:.1%} below 80%")
        if not gate_phash:
            failed_gates.append(f"- pHash success rate {phash_rate:.1%} below 80%")
        lines.extend(failed_gates)


def _gate_row(lines: list[str], name: str, threshold: str, actual: str, passed: bool) -> None:
    icon = "PASS" if passed else "FAIL"
    lines.append(f"| {name} | {threshold} | {actual} | **{icon}** |")


def _generate_json_summary(results: list[dict], elapsed: float) -> dict:
    """Generate ADR 020 JSON summary."""
    total = len(results)
    total_passed = sum(r["questions_passed"] for r in results)
    total_warning = sum(r["questions_warning"] for r in results)
    total_failed = sum(r["questions_failed"] for r in results)
    total_questions = total_passed + total_warning + total_failed

    pipeline_completed = sum(1 for r in results if r["status"] == "completed")
    pipeline_partial = sum(1 for r in results if r["status"] == "partial")
    pipeline_failed = sum(1 for r in results if r["status"] == "failed")

    all_warnings: Counter[str] = Counter()
    for r in results:
        for code, count in r["quality_warning_counts"].items():
            all_warnings[code] += count

    total_raw_assets = sum(r["raw_assets"] for r in results)
    total_qa_links = sum(r["qa_links"] for r in results if r["qa_links"] > 0)
    total_unlinked = sum(r["unlinked_raw_assets"] for r in results if r["unlinked_raw_assets"] > 0)
    total_broken_links = sum(
        r["links_without_question_block"] for r in results
        if r["links_without_question_block"] > 0
    )
    total_crop_success = sum(r["crop_success"] for r in results)
    total_crop_failed = sum(r["crop_failed"] for r in results)
    total_crop_attempts = total_crop_success + total_crop_failed
    total_phash = sum(r["phash_success"] for r in results)
    total_dup = sum(r["duplicate_candidates"] for r in results)
    total_vis = sum(r["visual_candidates"] for r in results)
    pdfs_with_assets = sum(1 for r in results if r["raw_assets"] > 0)

    # Acceptance gate checks
    success_total = pipeline_completed + pipeline_partial
    gate_success = success_total >= total * 0.9
    gate_no_failures = pipeline_failed == 0
    gate_no_failed_questions = total_failed == 0
    warning_ratio = total_warning / total_questions if total_questions > 0 else 0
    gate_warning = warning_ratio <= 0.1
    gate_assets = pdfs_with_assets >= total * 0.5
    gate_links = total_qa_links > 0
    unlinked_rate = total_unlinked / total_raw_assets if total_raw_assets > 0 else 0
    gate_unlinked = unlinked_rate <= 0.1
    gate_link_integrity = total_broken_links == 0
    crop_rate = total_crop_success / total_crop_attempts if total_crop_attempts > 0 else 1.0
    gate_crop = crop_rate >= 0.8
    phash_rate = total_phash / total_crop_success if total_crop_success > 0 else 1.0
    gate_phash = phash_rate >= 0.8

    all_passed = all([
        gate_success, gate_no_failures, gate_no_failed_questions,
        gate_warning, gate_assets, gate_links, gate_unlinked,
        gate_link_integrity, gate_crop, gate_phash,
    ])

    return {
        "evaluation": "ADR 020 — Small-Scale Real Ingestion Beta",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_pdfs": total,
        "pipeline_completed": pipeline_completed,
        "pipeline_partial": pipeline_partial,
        "pipeline_failed": pipeline_failed,
        "success_rate": round(success_total / total * 100, 1) if total > 0 else 0,
        "total_questions": total_questions,
        "questions_passed": total_passed,
        "questions_warning": total_warning,
        "questions_failed": total_failed,
        "quality_warning_counts": dict(all_warnings.most_common()),
        "failed_question_ids": [
            {"paper_id": r["paper_id"], "question_id": qid}
            for r in results
            for qid in r["failed_question_ids"]
        ],
        # Asset metrics
        "total_raw_assets": total_raw_assets,
        "total_question_asset_links": total_qa_links,
        "unlinked_raw_assets": total_unlinked,
        "links_without_question_block": total_broken_links,
        "crop_success": total_crop_success,
        "crop_failed": total_crop_failed,
        "phash_computed": total_phash,
        "duplicate_candidate_groups": total_dup,
        "visual_candidate_groups": total_vis,
        "pdfs_with_assets": pdfs_with_assets,
        # Acceptance gates
        "gates": {
            "success_rate_90pct": {"threshold": ">= 90%", "actual": f"{success_total / total * 100:.1f}%" if total > 0 else "0%", "passed": gate_success},
            "pipeline_failed_0": {"threshold": "0", "actual": pipeline_failed, "passed": gate_no_failures},
            "questions_failed_0": {"threshold": "0", "actual": total_failed, "passed": gate_no_failed_questions},
            "warning_rate_10pct": {"threshold": "<= 10%", "actual": f"{warning_ratio:.1%}", "passed": gate_warning},
            "pdfs_with_assets_50pct": {"threshold": ">= 50%", "actual": f"{pdfs_with_assets}/{total}", "passed": gate_assets},
            "question_asset_links_gt_0": {"threshold": "> 0", "actual": total_qa_links, "passed": gate_links},
            "unlinked_raw_assets_10pct": {"threshold": "<= 10%", "actual": f"{unlinked_rate:.1%}", "passed": gate_unlinked},
            "links_without_question_block_0": {"threshold": "0", "actual": total_broken_links, "passed": gate_link_integrity},
            "crop_success_80pct": {"threshold": ">= 80%", "actual": f"{crop_rate:.1%}", "passed": gate_crop},
            "phash_success_80pct": {"threshold": ">= 80%", "actual": f"{phash_rate:.1%}", "passed": gate_phash},
        },
        "elapsed_s": round(elapsed, 1),
        "verdict": "PASS" if all_passed else "BLOCKED",
        "papers": [
            {
                "paper_id": r["paper_id"],
                "status": r["status"],
                "pages": r["pages"],
                "layout_q": r["layout_q"],
                "deepseek_out": r["deepseek_out"],
                "questions_passed": r["questions_passed"],
                "questions_warning": r["questions_warning"],
                "questions_failed": r["questions_failed"],
                "failed_question_ids": r["failed_question_ids"],
                "quality_warning_counts": r["quality_warning_counts"],
                "raw_assets": r["raw_assets"],
                "qa_links": r["qa_links"],
                "unlinked_raw_assets": r["unlinked_raw_assets"],
                "links_without_question_block": r["links_without_question_block"],
                "crop_success": r["crop_success"],
                "crop_failed": r["crop_failed"],
                "phash_success": r["phash_success"],
                "duplicate_candidates": r["duplicate_candidates"],
                "visual_candidates": r["visual_candidates"],
                "elapsed_s": r["elapsed_s"],
                "retry_count": r.get("retry_count", 0),
                "previous_error": r.get("previous_error"),
                "error": r["error"][:200] if r["error"] else None,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Progress display
# ---------------------------------------------------------------------------


def _print_progress(n: int, total: int, paper_id: str, elapsed: float) -> None:
    bar_width = 30
    filled = int(bar_width * n / total)
    bar = "█" * filled + "░" * (bar_width - filled)
    eta = (elapsed / n * (total - n)) if n > 0 else 0
    print(f"\r  [{bar}] {n}/{total} | {paper_id:<24} | "
          f"elapsed={elapsed:.0f}s eta={eta:.0f}s", end="", flush=True)


# ---------------------------------------------------------------------------
# ADR 021: Summarize from existing run-report.json files
# ---------------------------------------------------------------------------


def _summarize_from_existing(
    work_root: Path,
    pdf_paths: list[Path],
    prefix: str,
    repository,
) -> list[dict]:
    """ADR 021: recompute results from existing run-report.json files.

    Does NOT re-run ingestion. Reads run-report.json from each work_dir
    and queries the DB for asset link integrity.
    """
    results: list[dict] = []
    for i, pdf_path in enumerate(pdf_paths):
        n = i + 1
        paper_id = f"{prefix}_{n:04d}"
        work_dir = work_root / paper_id
        report_path = work_dir / "run-report.json"

        if not report_path.exists():
            results.append({
                "paper_id": paper_id,
                "pdf_path": str(pdf_path),
                "work_dir": str(work_dir),
                "status": "missing_report",
                "pages": None,
                "layout_q": 0,
                "deepseek_out": 0,
                "questions_passed": 0,
                "questions_warning": 0,
                "questions_failed": 0,
                "failed_question_ids": [],
                "quality_warning_counts": {},
                "raw_assets": 0,
                "qa_links": 0,
                "unlinked_raw_assets": 0,
                "links_without_question_block": 0,
                "crop_success": 0,
                "crop_failed": 0,
                "phash_success": 0,
                "duplicate_candidates": 0,
                "visual_candidates": 0,
                "elapsed_s": 0,
                "retry_count": 0,
                "previous_error": None,
                "error": "run-report.json not found",
            })
            continue

        try:
            report_data = json.loads(report_path.read_text(encoding="utf-8"))
            status = report_data.get("status", "unknown")
            steps_map: dict[str, dict] = {}
            for s in report_data.get("steps", []):
                steps_map[s.get("name", "")] = s

            layout_q = steps_map.get("layout_ownership", {}).get("output_count", 0)
            deepseek_out = steps_map.get("deepseek_structure", {}).get("output_count", 0)
            raw_assets_count = steps_map.get("identify_assets", {}).get("output_count", 0)
            crop_data = steps_map.get("crop_assets", {})
            crop_success = crop_data.get("output_count", 0)
            crop_warnings = crop_data.get("warnings", [])
            crop_failed = len(crop_warnings)
            phash_success = steps_map.get("compute_phash", {}).get("output_count", 0)
            dup_candidates = steps_map.get("duplicate_candidates", {}).get("output_count", 0)
            vis_candidates = steps_map.get("visual_candidates", {}).get("output_count", 0)

            # DB queries for asset link integrity
            qa_links = -1
            unlinked_raw_assets = -1
            links_without_qb = -1
            db_available = False
            if repository is not None:
                try:
                    cursor = repository.connection.cursor()
                    cursor.execute(
                        """SELECT COUNT(*)
                           FROM question_asset_links qal
                           JOIN raw_assets ra ON ra.id = qal.raw_asset_id
                           WHERE ra.paper_id = %(paper_id)s""",
                        {"paper_id": paper_id},
                    )
                    row = cursor.fetchone()
                    qa_links = (row[0] if isinstance(row, tuple) else row.get("count", 0)) if row else 0

                    cursor.execute(
                        """SELECT COUNT(*)
                           FROM raw_assets ra
                           WHERE ra.paper_id = %(paper_id)s
                             AND NOT EXISTS (
                                 SELECT 1 FROM question_asset_links qal
                                 WHERE qal.raw_asset_id = ra.id
                             )""",
                        {"paper_id": paper_id},
                    )
                    row = cursor.fetchone()
                    unlinked_raw_assets = (row[0] if isinstance(row, tuple) else row.get("count", 0)) if row else 0

                    cursor.execute(
                        """SELECT COUNT(*)
                           FROM question_asset_links qal
                           JOIN raw_assets ra ON ra.id = qal.raw_asset_id
                           LEFT JOIN question_blocks qb ON qb.id = qal.question_id
                           WHERE ra.paper_id = %(paper_id)s AND qb.id IS NULL""",
                        {"paper_id": paper_id},
                    )
                    row = cursor.fetchone()
                    links_without_qb = (row[0] if isinstance(row, tuple) else row.get("count", 0)) if row else 0
                    db_available = True
                except Exception:
                    pass

            if not db_available:
                raise RuntimeError(
                    "Database unavailable for asset link queries — "
                    "required by --summarize-existing"
                )

            # Retry tracking from previous report
            prev_report_path = work_dir / "run-report.previous.json"
            retry_count = 0
            previous_error = None
            if prev_report_path.exists():
                retry_count = 1
                try:
                    prev_data = json.loads(prev_report_path.read_text(encoding="utf-8"))
                    prev_status = prev_data.get("status", "unknown")
                    if prev_status == "failed":
                        prev_errors = prev_data.get("errors", [])
                        previous_error = "; ".join(prev_errors[:3]) if prev_errors else "previous run failed"
                    else:
                        previous_error = f"previous status: {prev_status}"
                except Exception:
                    previous_error = "previous report unparseable"

            # Page count from PDF
            pages = count_pages(pdf_path)

            # Elapsed time from report
            started = report_data.get("started_at", "")
            finished = report_data.get("finished_at", "")
            elapsed_s = 0
            try:
                from datetime import datetime as dt
                if started and finished:
                    t0 = dt.fromisoformat(started)
                    t1 = dt.fromisoformat(finished)
                    elapsed_s = round((t1 - t0).total_seconds(), 1)
            except Exception:
                pass

            results.append({
                "paper_id": paper_id,
                "pdf_path": str(pdf_path),
                "work_dir": str(work_dir),
                "status": status,
                "pages": pages,
                "layout_q": layout_q,
                "deepseek_out": deepseek_out,
                "questions_passed": report_data.get("questions_passed", 0),
                "questions_warning": report_data.get("questions_warning", 0),
                "questions_failed": report_data.get("questions_failed", 0),
                "failed_question_ids": report_data.get("failed_question_ids", []),
                "quality_warning_counts": report_data.get("quality_warning_counts", {}),
                "raw_assets": raw_assets_count,
                "qa_links": qa_links,
                "unlinked_raw_assets": unlinked_raw_assets,
                "links_without_question_block": links_without_qb,
                "crop_success": crop_success,
                "crop_failed": crop_failed,
                "phash_success": phash_success,
                "duplicate_candidates": dup_candidates,
                "visual_candidates": vis_candidates,
                "elapsed_s": elapsed_s,
                "retry_count": retry_count,
                "previous_error": previous_error,
                "error": None if status != "failed" else (
                    "; ".join(report_data.get("errors", [])[:3]) or "pipeline failed"
                ),
            })
        except RuntimeError as exc:
            if "Database unavailable" in str(exc):
                raise
            results.append({
                "paper_id": paper_id,
                "pdf_path": str(pdf_path),
                "work_dir": str(work_dir),
                "status": "error",
                "pages": None,
                "layout_q": 0,
                "deepseek_out": 0,
                "questions_passed": 0,
                "questions_warning": 0,
                "questions_failed": 0,
                "failed_question_ids": [],
                "quality_warning_counts": {},
                "raw_assets": 0,
                "qa_links": -1,
                "unlinked_raw_assets": -1,
                "links_without_question_block": -1,
                "crop_success": 0,
                "crop_failed": 0,
                "phash_success": 0,
                "duplicate_candidates": 0,
                "visual_candidates": 0,
                "elapsed_s": 0,
                "retry_count": 0,
                "previous_error": None,
                "error": str(exc),
            })
        except Exception as exc:
            results.append({
                "paper_id": paper_id,
                "pdf_path": str(pdf_path),
                "work_dir": str(work_dir),
                "status": "error",
                "pages": None,
                "layout_q": 0,
                "deepseek_out": 0,
                "questions_passed": 0,
                "questions_warning": 0,
                "questions_failed": 0,
                "failed_question_ids": [],
                "quality_warning_counts": {},
                "raw_assets": 0,
                "qa_links": -1,
                "unlinked_raw_assets": -1,
                "links_without_question_block": -1,
                "crop_success": 0,
                "crop_failed": 0,
                "phash_success": 0,
                "duplicate_candidates": 0,
                "visual_candidates": 0,
                "elapsed_s": 0,
                "retry_count": 0,
                "previous_error": None,
                "error": str(exc),
            })

    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # ADR 021: --summarize-existing mode
    if args.summarize_existing:
        return _main_summarize_existing(args)

    if not args.pdf_dir:
        print("ERROR: --pdf-dir is required unless --summarize-existing is used.",
              file=sys.stderr)
        return 1

    pdf_dir = Path(args.pdf_dir)
    if not pdf_dir.is_dir():
        print(f"ERROR: PDF directory not found: {pdf_dir}", file=sys.stderr)
        return 1

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"ERROR: No PDF files found in {pdf_dir}", file=sys.stderr)
        return 1

    # ADR 021: --only-index or --only-paper filtering
    if args.only_index is not None:
        idx = args.only_index - 1  # convert to 0-indexed
        if 0 <= idx < len(pdf_files):
            pdf_files = [pdf_files[idx]]
        else:
            print(f"ERROR: --only-index {args.only_index} out of range "
                  f"(1-{len(pdf_files)})", file=sys.stderr)
            return 1
    elif args.only_paper:
        matched = [p for p in pdf_files if args.only_paper in p.stem]
        if matched:
            pdf_files = matched
        else:
            print(f"ERROR: --only-paper '{args.only_paper}' matched no PDFs in {pdf_dir}",
                  file=sys.stderr)
            return 1

    if args.limit:
        pdf_files = pdf_files[:args.limit]

    today = datetime.now().strftime("%Y-%m-%d")
    work_root = args.work_root or Path(f"data/runs/real_beta_{today}")
    work_root.mkdir(parents=True, exist_ok=True)

    # Lazy imports
    from question_bank.config import Settings, psycopg_conninfo
    from question_bank.services.deepseek import DeepSeekHTTPClient

    settings = Settings.load()

    api_key = settings.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY not configured.", file=sys.stderr)
        print("Set DEEPSEEK_API_KEY in .env or environment.", file=sys.stderr)
        return 1

    deepseek_client = DeepSeekHTTPClient(
        api_key=api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
    )

    try:
        import psycopg
        from question_bank.repository import PostgresQuestionBankRepository
    except ImportError:
        print("ERROR: psycopg is required (non-dry-run mode).", file=sys.stderr)
        print("Install project dependencies first.", file=sys.stderr)
        return 2

    repository = PostgresQuestionBankRepository(
        psycopg.connect(psycopg_conninfo(settings.database_url))
    )

    print(f"ADR 020/021 — Small-Scale Real Ingestion Beta")
    print(f"PDFs: {len(pdf_files)} from {pdf_dir}")
    print(f"Resume: {args.resume}")
    print(f"Work root: {work_root}")
    print(f"Paper prefix: {args.paper_prefix}")
    print()

    results: list[dict] = []
    start_time = time.monotonic()

    for i, pdf_path in enumerate(pdf_files):
        n = i + 1
        total = len(pdf_files)
        elapsed = time.monotonic() - start_time
        _print_progress(n, total, pdf_path.stem, elapsed)

        result = _process_one_safe(
            pdf_path=pdf_path,
            index=n,
            prefix=args.paper_prefix,
            work_root=work_root,
            asset_dir=args.asset_dir,
            resume=args.resume,
            deepseek_client=deepseek_client,
            mineru_command=settings.mineru_command,
            repository=repository,
        )
        results.append(result)

    print()
    return _output_reports(results, work_root, args.report_dir, today)


def _main_summarize_existing(args) -> int:
    """ADR 021: --summarize-existing mode."""
    if not args.work_root:
        print("ERROR: --work-root is required with --summarize-existing",
              file=sys.stderr)
        return 1

    work_root = Path(args.work_root)
    if not work_root.is_dir():
        print(f"ERROR: work root not found: {work_root}", file=sys.stderr)
        return 1

    today = datetime.now().strftime("%Y-%m-%d")

    # Discover paper dirs from work_root
    paper_dirs = sorted(
        d for d in work_root.iterdir()
        if d.is_dir() and (d / "run-report.json").exists()
    )

    if args.only_index is not None:
        idx = args.only_index - 1
        if 0 <= idx < len(paper_dirs):
            paper_dirs = [paper_dirs[idx]]
        else:
            print(f"ERROR: --only-index {args.only_index} out of range "
                  f"(1-{len(paper_dirs)})", file=sys.stderr)
            return 1
    elif args.only_paper:
        matched = [d for d in paper_dirs if args.only_paper in d.name]
        if matched:
            paper_dirs = matched
        else:
            print(f"ERROR: --only-paper '{args.only_paper}' matched no dirs",
                  file=sys.stderr)
            return 1

    # Build synthetic pdf_paths (for page counting)
    synthetic_paths = [d / "placeholder.pdf" for d in paper_dirs]

    # DB connection
    from question_bank.config import Settings, psycopg_conninfo
    settings = Settings.load()

    try:
        import psycopg
        from question_bank.repository import PostgresQuestionBankRepository
    except ImportError:
        print("ERROR: psycopg is required.", file=sys.stderr)
        return 2

    repository = PostgresQuestionBankRepository(
        psycopg.connect(psycopg_conninfo(settings.database_url))
    )

    print(f"ADR 021 — Summarize Existing Run Reports")
    print(f"Paper dirs: {len(paper_dirs)} from {work_root}")
    print(f"Prefix: {args.paper_prefix}")
    print()

    results = _summarize_from_existing(
        work_root, synthetic_paths, args.paper_prefix, repository,
    )

    return _output_reports(results, work_root, args.report_dir, today)


def _output_reports(
    results: list[dict],
    work_root: Path,
    report_dir: Path,
    today: str,
) -> int:
    """Write markdown + JSON reports and print summary."""
    total_elapsed = sum(r["elapsed_s"] for r in results)

    # Generate markdown report
    report_md = _generate_markdown_report(results, total_elapsed)
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / f"real-e2e-beta-{today}.md"
    md_path.write_text(report_md, encoding="utf-8")

    # Generate JSON summary
    summary_json = _generate_json_summary(results, total_elapsed)
    json_path = work_root / f"real-e2e-beta-summary-{today}.json"
    json_path.write_text(json.dumps(summary_json, indent=2, ensure_ascii=False))

    # Print summary
    total_passed_q = sum(r["questions_passed"] for r in results)
    total_warning_q = sum(r["questions_warning"] for r in results)
    total_failed_q = sum(r["questions_failed"] for r in results)
    total_questions = total_passed_q + total_warning_q + total_failed_q
    pipeline_completed = sum(1 for r in results if r["status"] == "completed")
    pipeline_failed = sum(1 for r in results if r["status"] == "failed")

    print(f"\nResults: {pipeline_completed} completed, {pipeline_failed} failed "
          f"of {len(results)} PDFs")
    print(f"Questions: {total_passed_q} passed, {total_warning_q} warning, "
          f"{total_failed_q} failed (of {total_questions})")
    print(f"Report: {md_path}")
    print(f"Summary: {json_path}")

    verdict = summary_json["verdict"]
    print(f"Verdict: {verdict}")

    if verdict == "BLOCKED":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
