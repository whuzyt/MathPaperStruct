"""ADR 022: Production Batch Runner & Observability.

Non-dry-run batch ingestion with manifest-driven recovery, step-level timing,
failure taxonomy, and throughput reporting.

Usage:
  python3 tools/batch_real_ingest.py --pdf-dir data/beta/pdf --limit 100
  python3 tools/batch_real_ingest.py --pdf-dir data/beta/pdf --resume
  python3 tools/batch_real_ingest.py --pdf-dir data/beta/pdf --only-index 12
  python3 tools/batch_real_ingest.py --pdf-dir data/beta/pdf --fail-fast
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.eval_deepseek_structure import count_pages


# ---------------------------------------------------------------------------
# Manifest data structures
# ---------------------------------------------------------------------------


MANIFEST_STATUSES = frozenset({
    "pending", "running", "completed", "partial", "failed", "crashed",
})

REQUIRED_SCHEMA_TABLES = (
    "papers",
    "question_blocks",
    "questions",
    "choices",
    "quality_reports",
    "raw_assets",
    "question_asset_links",
    "duplicate_candidate_groups",
    "canonical_questions",
    "canonical_assets",
)


def _init_manifest(
    pdf_files: list[Path],
    prefix: str,
    work_root: Path,
) -> list[dict]:
    """Create fresh manifest entries for a batch of PDFs."""
    manifest: list[dict] = []
    for i, pdf_path in enumerate(pdf_files):
        paper_id = f"{prefix}_{i + 1:04d}"
        manifest.append({
            "paper_id": paper_id,
            "pdf_path": str(pdf_path),
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "attempts": 0,
            "last_error": None,
            "run_report_path": None,
        })
    return manifest


def _load_manifest(work_root: Path) -> list[dict] | None:
    """Load existing batch-manifest.json. Returns None if missing or corrupt."""
    manifest_path = work_root / "batch-manifest.json"
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return None


def _save_manifest(manifest: list[dict], work_root: Path) -> None:
    """Persist manifest to work_root/batch-manifest.json."""
    manifest_path = work_root / "batch-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _update_manifest_entry(
    manifest: list[dict],
    paper_id: str,
    **kwargs,
) -> None:
    """Update a manifest entry in place by paper_id."""
    for entry in manifest:
        if entry["paper_id"] == paper_id:
            entry.update(kwargs)
            return


def _split_manifest_paper_id(paper_id: str, fallback_prefix: str) -> tuple[str, int]:
    """Return the stable prefix/index encoded in a manifest paper_id."""
    prefix, sep, suffix = paper_id.rpartition("_")
    if sep and suffix.isdigit():
        return prefix, int(suffix)
    return fallback_prefix, 1


# ---------------------------------------------------------------------------
# ADR 023: production preflight gate
# ---------------------------------------------------------------------------


def _validate_deepseek_api_key(api_key: str | None) -> str | None:
    """Return an error if the DeepSeek API key is absent or obviously invalid."""
    if not api_key or not api_key.strip():
        return "DEEPSEEK_API_KEY not configured. Set it in .env or environment."
    key = api_key.strip()
    if key in {"sk-...", "sk-test", "sk-xxx"}:
        return "DEEPSEEK_API_KEY looks like a placeholder."
    if not key.startswith("sk-"):
        return "DEEPSEEK_API_KEY must start with sk-."
    if len(key) < 8:
        return "DEEPSEEK_API_KEY is too short."
    return None


def _validate_mineru_command(command: str) -> str | None:
    """Return an error if the configured MinerU command cannot be resolved."""
    if not command or not command.strip():
        return "MinerU command is empty. Set MINERU_COMMAND or install mineru."

    command = command.strip()
    is_path_like = "/" in command or command.startswith(".")
    if is_path_like:
        if Path(command).exists():
            return None
        return (
            f"MinerU command not found: {command}. "
            "Set MINERU_COMMAND to the installed mineru executable."
        )

    if shutil.which(command):
        return None
    return (
        f"MinerU command not found on PATH: {command}. "
        "Install MinerU or set MINERU_COMMAND."
    )


def _ensure_writable_dir(path: Path, label: str) -> str | None:
    """Create and probe a writable directory used by production batch output."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".preflight_write_test_{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return None
    except Exception as exc:
        return f"{label} is not writable: {path} ({exc})"


def _missing_schema_tables(connection) -> list[str]:
    """Return required DB tables absent from the configured PostgreSQL schema."""
    cursor = connection.cursor()
    missing: list[str] = []
    for table in REQUIRED_SCHEMA_TABLES:
        cursor.execute("SELECT to_regclass(%s)", (f"public.{table}",))
        row = cursor.fetchone()
        value = row[0] if isinstance(row, tuple) else (row.get("to_regclass") if row else None)
        if value is None:
            missing.append(table)
    return missing


def _open_checked_database_connection(settings, psycopg_module):
    """Open PostgreSQL and verify minimal production schema before batch work."""
    from question_bank.config import psycopg_conninfo

    try:
        connection = psycopg_module.connect(psycopg_conninfo(settings.database_url))
    except Exception as exc:
        raise RuntimeError(f"PostgreSQL connection failed: {exc}") from exc

    try:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        missing = _missing_schema_tables(connection)
    except Exception as exc:
        try:
            connection.close()
        except Exception:
            pass
        raise RuntimeError(f"PostgreSQL preflight query failed: {exc}") from exc

    if missing:
        try:
            connection.close()
        except Exception:
            pass
        missing_text = ", ".join(missing)
        raise RuntimeError(
            "Database schema missing tables: "
            f"{missing_text}. Run `PYTHONPATH=src python3 -m question_bank.cli db init`."
        )

    return connection


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Production batch real ingestion runner (ADR 022)"
    )
    parser.add_argument(
        "--pdf-dir", type=Path, required=True,
        help="Directory containing PDF files to process")
    parser.add_argument(
        "--work-root", type=Path, default=None,
        help="Root for per-paper work dirs (default: data/runs/batch_<date>)")
    parser.add_argument(
        "--asset-dir", type=Path, default=Path("data/assets"),
        help="Asset storage directory (default: data/assets)")
    parser.add_argument(
        "--paper-prefix", type=str, default=None,
        help="Prefix for paper IDs (default: derived from work-root or 'batch')")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max number of PDFs to process")
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from existing batch-manifest.json")
    parser.add_argument(
        "--only-index", type=int, default=None,
        help="Process only the Nth PDF (1-indexed)")
    parser.add_argument(
        "--only-paper", type=str, default=None,
        help="Process only the PDF matching this paper ID substring")
    parser.add_argument(
        "--fail-fast", action="store_true",
        help="Stop on first failure instead of continuing")
    parser.add_argument(
        "--report-dir", type=Path, default=Path("docs/eval"),
        help="Output directory for batch report (default: docs/eval)")
    return parser


# ---------------------------------------------------------------------------
# Per-paper processing (reuses eval_real_e2e_beta helpers)
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

    step_data: dict[str, dict] = {}
    for s in report.steps:
        step_data[s.name] = {
            "status": s.status,
            "output_count": s.output_count,
            "started_at": s.started_at,
            "finished_at": s.finished_at,
            "warnings": s.warnings,
            "error": s.error,
        }

    layout_q = step_data.get("layout_ownership", {}).get("output_count", 0)
    deepseek_out = step_data.get("deepseek_structure", {}).get("output_count", 0)
    raw_assets = step_data.get("identify_assets", {}).get("output_count", 0)
    crop_success = step_data.get("crop_assets", {}).get("output_count", 0)
    crop_warnings = step_data.get("crop_assets", {}).get("warnings", [])
    crop_failed = len(crop_warnings)
    phash_success = step_data.get("compute_phash", {}).get("output_count", 0)
    duplicate_candidates = step_data.get("duplicate_candidates", {}).get("output_count", 0)
    visual_candidates = step_data.get("visual_candidates", {}).get("output_count", 0)

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

    pages = count_pages(pdf_path)
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
        "step_data": step_data,
        "error": error,
    }


def _report_error_summary(report) -> str | None:
    errors = getattr(report, "errors", None) or []
    if errors:
        return "; ".join(str(e) for e in errors if str(e).strip()) or None
    failed_steps = []
    for step in getattr(report, "steps", []):
        if getattr(step, "status", "") == "failed":
            name = getattr(step, "name", "unknown")
            err = getattr(step, "error", None)
            failed_steps.append(f"{name}: {err}" if err else name)
    return "; ".join(failed_steps) if failed_steps else None


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
    """Wrap _process_one_pdf with failure isolation."""
    paper_id = f"{prefix}_{index:04d}"
    work_dir = work_root / paper_id

    try:
        return _process_one_pdf(
            pdf_path, index, prefix, work_root, asset_dir,
            resume, deepseek_client, mineru_command, repository,
        )
    except Exception as exc:
        return {
            "paper_id": paper_id,
            "pdf_path": str(pdf_path),
            "work_dir": str(work_dir),
            "status": "crashed",
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
            "step_data": {},
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Failure taxonomy (ADR 022)
# ---------------------------------------------------------------------------


def _classify_failure(error_text: str) -> str:
    """ADR 022: classify a failure into a taxonomy category."""
    if not error_text:
        return "unknown"
    text = error_text.lower()
    if "mineru" in text or "mineru" in text.lower():
        for transient in (
            "connection", "timeout", "timed out", "refused",
            "reset", "broken pipe", "unreachable",
        ):
            if transient in text:
                return "mineru_transient"
        return "mineru_non_transient"
    if "deepseek" in text:
        return "deepseek"
    if "database" in text or "psycopg" in text or "postgres" in text:
        return "database"
    if "layout" in text:
        return "layout"
    if "crop" in text:
        return "asset_crop"
    if "store" in text or "storage" in text:
        return "asset_store"
    return "unknown"


# ---------------------------------------------------------------------------
# Step timing extraction
# ---------------------------------------------------------------------------


def _extract_step_timings(results: list[dict]) -> list[dict]:
    """ADR 022: extract step-level timing from run results.

    Each result may contain step_data with started_at/finished_at for each step.
    Returns a list of {step_name, total_s, count, avg_s, max_s, slowest_paper}.
    """
    step_accum: dict[str, dict] = {}

    for r in results:
        step_data = r.get("step_data", {})
        if not step_data:
            continue
        for step_name, sd in step_data.items():
            if step_name not in step_accum:
                step_accum[step_name] = {
                    "total_s": 0.0,
                    "count": 0,
                    "max_s": 0.0,
                    "slowest_paper": None,
                }
            started = sd.get("started_at", "")
            finished = sd.get("finished_at", "")
            if started and finished:
                try:
                    from datetime import datetime as dt
                    t0 = dt.fromisoformat(started)
                    t1 = dt.fromisoformat(finished)
                    dur = (t1 - t0).total_seconds()
                except Exception:
                    dur = 0.0
                acc = step_accum[step_name]
                acc["total_s"] += dur
                acc["count"] += 1
                if dur > acc["max_s"]:
                    acc["max_s"] = dur
                    acc["slowest_paper"] = r["paper_id"]

    result = []
    for step_name, acc in sorted(step_accum.items()):
        if acc["count"] == 0:
            continue
        result.append({
            "step": step_name,
            "total_s": round(acc["total_s"], 1),
            "count": acc["count"],
            "avg_s": round(acc["total_s"] / acc["count"], 1) if acc["count"] else 0,
            "max_s": round(acc["max_s"], 1),
            "slowest_paper": acc["slowest_paper"],
            "pct_of_wall": 0.0,  # filled by caller with wall clock
        })
    return result


# ---------------------------------------------------------------------------
# Progress display
# ---------------------------------------------------------------------------


def _print_progress(n: int, total: int, paper_id: str, elapsed: float) -> None:
    bar_width = 30
    filled = int(bar_width * n / total) if total > 0 else bar_width
    bar = "█" * filled + "░" * (bar_width - filled)
    eta = (elapsed / n * (total - n)) if n > 0 else 0
    print(f"\r  [{bar}] {n}/{total} | {paper_id:<24} | "
          f"elapsed={elapsed:.0f}s eta={eta:.0f}s", end="", flush=True)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _generate_markdown_report(
    results: list[dict],
    wall_elapsed: float,
    manifest: list[dict],
    step_timings: list[dict],
    failure_taxonomy: Counter[str],
    failure_examples: dict[str, str],
) -> str:
    """ADR 022: comprehensive batch markdown report."""
    today = datetime.now().strftime("%Y-%m-%d")
    total = len(results)

    total_passed = sum(r["questions_passed"] for r in results)
    total_warning = sum(r["questions_warning"] for r in results)
    total_failed = sum(r["questions_failed"] for r in results)
    total_questions = total_passed + total_warning + total_failed

    completed = sum(1 for r in results if r["status"] == "completed")
    partial = sum(1 for r in results if r["status"] == "partial")
    failed = sum(1 for r in results if r["status"] == "failed")
    crashed = sum(1 for r in results if r["status"] == "crashed")

    total_raw_assets = sum(r["raw_assets"] for r in results)
    total_qa_links = sum(r["qa_links"] for r in results if r["qa_links"] > 0)
    total_crop_success = sum(r["crop_success"] for r in results)
    total_crop_failed = sum(r["crop_failed"] for r in results)
    total_phash = sum(r["phash_success"] for r in results)

    # Throughput metrics
    total_pages = sum(r["pages"] for r in results if r["pages"])
    pdfs_with_pages = sum(1 for r in results if r["pages"])

    lines: list[str] = []
    lines.append(f"# Production Batch Ingestion — {today}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total PDFs | {total} |")
    lines.append(f"| Completed | {completed} |")
    lines.append(f"| Partial | {partial} |")
    lines.append(f"| Failed | {failed} |")
    lines.append(f"| Crashed | {crashed} |")
    if total > 0:
        success_rate = (completed + partial) / total * 100
        lines.append(f"| Success rate | {success_rate:.1f}% |")
    lines.append(f"| Total questions | {total_questions} |")
    lines.append(f"| Questions passed | {total_passed} |")
    lines.append(f"| Questions warning | {total_warning} |")
    lines.append(f"| Questions failed | {total_failed} |")
    lines.append("")

    # Throughput
    lines.append("## Throughput")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Wall clock | {wall_elapsed:.0f}s |")
    if total > 0:
        lines.append(f"| Avg sec/PDF | {wall_elapsed / total:.1f}s |")
    if pdfs_with_pages > 0 and total_pages > 0:
        lines.append(f"| Total pages | {total_pages} |")
        lines.append(f"| Avg sec/page | {wall_elapsed / total_pages:.1f}s |")
    if total_questions > 0:
        lines.append(f"| Avg sec/question | {wall_elapsed / total_questions:.1f}s |")
    lines.append("")

    # Asset pipeline
    lines.append("## Asset Pipeline")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total raw_assets | {total_raw_assets} |")
    lines.append(f"| Total QA links | {total_qa_links} |")
    lines.append(f"| Crop success | {total_crop_success} |")
    lines.append(f"| Crop failed | {total_crop_failed} |")
    total_crop_attempts = total_crop_success + total_crop_failed
    if total_crop_attempts > 0:
        lines.append(f"| Crop success rate | {total_crop_success / total_crop_attempts * 100:.1f}% |")
    lines.append(f"| pHash computed | {total_phash} |")
    lines.append("")

    # Step timing
    if step_timings:
        lines.append("## Step Timing")
        lines.append("")
        lines.append("| Step | Count | Total (s) | Avg (s) | Max (s) | % Wall | Slowest |")
        lines.append("|------|-------|-----------|---------|---------|--------|---------|")
        for st in step_timings:
            lines.append(
                f"| {st['step']} | {st['count']} | {st['total_s']} | "
                f"{st['avg_s']} | {st['max_s']} | "
                f"{st['pct_of_wall']:.0f}% | "
                f"{st.get('slowest_paper') or '-'} |"
            )
        lines.append("")

    # Failure taxonomy
    if failure_taxonomy:
        lines.append("## Failure Taxonomy")
        lines.append("")
        lines.append("| Category | Count | Example |")
        lines.append("|----------|-------|---------|")
        for category, count in failure_taxonomy.most_common():
            example = failure_examples.get(category, "-")[:100]
            lines.append(f"| {category} | {count} | {example} |")
        lines.append("")

    # Per-paper results
    lines.append("## Per-Paper Results")
    lines.append("")
    header = ("| Paper ID | Pg | Layout | Struct | Pass | Warn | Fail | "
              "Assets | Links | CropOK | CropFail | pHash | Status |")
    sep = ("|----------|----|--------|--------|------|------|------|"
           "--------|-------|--------|----------|-------|--------|")
    lines.append(header)
    lines.append(sep)
    for r in results:
        pg = str(r["pages"] or "?")
        lines.append(
            f"| {r['paper_id']} | {pg} | {r['layout_q']} | {r['deepseek_out']} | "
            f"{r['questions_passed']} | {r['questions_warning']} | {r['questions_failed']} | "
            f"{r['raw_assets']} | {r['qa_links']} | {r['crop_success']} | {r['crop_failed']} | "
            f"{r['phash_success']} | {r['status']} |"
        )
    lines.append("")

    # Quality warning distribution
    warning_counter: Counter[str] = Counter()
    for r in results:
        for code, count in r.get("quality_warning_counts", {}).items():
            warning_counter[code] += count
    if warning_counter:
        lines.append("## Quality Warning Distribution")
        lines.append("")
        lines.append("| Warning Code | Count |")
        lines.append("|--------------|-------|")
        for code, count in warning_counter.most_common():
            lines.append(f"| {code} | {count} |")
        lines.append("")

    # Errors detail
    error_results = [r for r in results if r["error"]]
    if error_results:
        lines.append("## Errors")
        lines.append("")
        lines.append("| Paper ID | Status | Error |")
        lines.append("|----------|--------|-------|")
        for r in error_results:
            lines.append(f"| {r['paper_id']} | {r['status']} | {r['error'][:150]} |")
        lines.append("")

    return "\n".join(lines) + "\n"


def _generate_json_summary(
    results: list[dict],
    wall_elapsed: float,
    manifest: list[dict],
    step_timings: list[dict],
    failure_taxonomy: Counter[str],
) -> dict:
    """ADR 022: comprehensive JSON summary."""
    total = len(results)
    completed = sum(1 for r in results if r["status"] == "completed")
    partial = sum(1 for r in results if r["status"] == "partial")
    failed = sum(1 for r in results if r["status"] == "failed")
    crashed = sum(1 for r in results if r["status"] == "crashed")

    total_passed = sum(r["questions_passed"] for r in results)
    total_warning = sum(r["questions_warning"] for r in results)
    total_failed_q = sum(r["questions_failed"] for r in results)
    total_questions = total_passed + total_warning + total_failed_q

    total_pages = sum(r["pages"] for r in results if r["pages"])
    total_raw_assets = sum(r["raw_assets"] for r in results)
    total_qa_links = sum(r["qa_links"] for r in results if r["qa_links"] > 0)
    total_crop_success = sum(r["crop_success"] for r in results)
    total_crop_failed = sum(r["crop_failed"] for r in results)
    total_phash = sum(r["phash_success"] for r in results)

    return {
        "evaluation": "ADR 022 — Production Batch Runner",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "manifest": {
            "total": len(manifest),
            "pending": sum(1 for m in manifest if m["status"] == "pending"),
            "completed": sum(1 for m in manifest if m["status"] == "completed"),
            "partial": sum(1 for m in manifest if m["status"] == "partial"),
            "failed": sum(1 for m in manifest if m["status"] == "failed"),
            "crashed": sum(1 for m in manifest if m["status"] == "crashed"),
        },
        "results": {
            "total_pdfs": total,
            "completed": completed,
            "partial": partial,
            "failed": failed,
            "crashed": crashed,
            "success_rate": round((completed + partial) / total * 100, 1) if total > 0 else 0,
        },
        "questions": {
            "total": total_questions,
            "passed": total_passed,
            "warning": total_warning,
            "failed": total_failed_q,
        },
        "throughput": {
            "wall_elapsed_s": round(wall_elapsed, 1),
            "total_pages": total_pages,
            "avg_sec_per_pdf": round(wall_elapsed / total, 1) if total > 0 else 0,
            "avg_sec_per_page": round(wall_elapsed / total_pages, 1) if total_pages > 0 else 0,
            "avg_sec_per_question": round(wall_elapsed / total_questions, 1) if total_questions > 0 else 0,
        },
        "assets": {
            "total_raw_assets": total_raw_assets,
            "total_qa_links": total_qa_links,
            "crop_success": total_crop_success,
            "crop_failed": total_crop_failed,
            "phash_computed": total_phash,
        },
        "step_timing": [
            {
                "step": st["step"],
                "total_s": st["total_s"],
                "count": st["count"],
                "avg_s": st["avg_s"],
                "max_s": st["max_s"],
                "slowest_paper": st.get("slowest_paper"),
            }
            for st in step_timings
        ],
        "failure_taxonomy": dict(failure_taxonomy.most_common()),
        "elapsed_s": round(wall_elapsed, 1),
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
                "raw_assets": r["raw_assets"],
                "qa_links": r["qa_links"],
                "crop_success": r["crop_success"],
                "crop_failed": r["crop_failed"],
                "phash_success": r["phash_success"],
                "elapsed_s": r["elapsed_s"],
                "error": r["error"][:200] if r["error"] else None,
                "failure_category": _classify_failure(r["error"]) if r["error"] else None,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    pdf_dir = Path(args.pdf_dir)
    if not pdf_dir.is_dir():
        print(f"ERROR: PDF directory not found: {pdf_dir}", file=sys.stderr)
        return 1

    pdf_files = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        print(f"ERROR: No PDF files found in {pdf_dir}", file=sys.stderr)
        return 1

    today = datetime.now().strftime("%Y-%m-%d")
    work_root = args.work_root or Path(f"data/runs/batch_{today}")
    work_root.mkdir(parents=True, exist_ok=True)

    prefix = args.paper_prefix or f"batch_{today.replace('-', '_')}"
    if args.limit and not args.resume:
        pdf_files = pdf_files[:args.limit]

    # Manifest management
    manifest: list[dict]
    if args.resume:
        existing = _load_manifest(work_root)
        if existing:
            manifest = existing
            print("Resuming from existing batch-manifest.json")
        else:
            print("WARNING: --resume specified but no manifest found, initializing new")
            manifest = _init_manifest(pdf_files, prefix, work_root)
    else:
        manifest = _init_manifest(pdf_files, prefix, work_root)

    selected_manifest = manifest
    if args.limit and args.resume:
        selected_manifest = selected_manifest[:args.limit]

    # --only-index / --only-paper filtering
    if args.only_index is not None:
        idx = args.only_index - 1
        if 0 <= idx < len(selected_manifest):
            selected_manifest = [selected_manifest[idx]]
        else:
            print(f"ERROR: --only-index {args.only_index} out of range "
                  f"(1-{len(selected_manifest)})", file=sys.stderr)
            return 1
    elif args.only_paper:
        matched = [m for m in selected_manifest if args.only_paper in m["paper_id"]]
        if matched:
            selected_manifest = matched
        else:
            print(f"ERROR: --only-paper '{args.only_paper}' matched no entries in manifest",
                  file=sys.stderr)
            return 1

    # Determine which entries to process
    if args.resume:
        to_process = [
            m for m in selected_manifest
            if m["status"] in ("pending", "failed", "crashed", "running")
        ]
        skipped = len(selected_manifest) - len(to_process)
        if skipped > 0:
            print(f"Skipping {skipped} already-completed entries")
    else:
        to_process = [m for m in selected_manifest if m["status"] != "completed"]
        # Reset statuses for fresh run
        for m in to_process:
            m["status"] = "pending"
            m["started_at"] = None
            m["finished_at"] = None
            m["last_error"] = None

    total_to_run = len(to_process)
    if total_to_run == 0:
        print("Nothing to process — all entries completed.")
        return 0

    # Lazy imports — require DB and DeepSeek
    from question_bank.config import Settings
    from question_bank.services.deepseek import DeepSeekHTTPClient

    settings = Settings.load()

    api_key = settings.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY")
    preflight_errors = [
        e for e in (
            _validate_deepseek_api_key(api_key),
            _validate_mineru_command(settings.mineru_command),
            _ensure_writable_dir(work_root, "work-root"),
            _ensure_writable_dir(args.asset_dir, "asset-dir"),
            _ensure_writable_dir(args.report_dir, "report-dir"),
        )
        if e
    ]
    if preflight_errors:
        print("ERROR: Production preflight failed.", file=sys.stderr)
        for error in preflight_errors:
            print(f"- {error}", file=sys.stderr)
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

    try:
        connection = _open_checked_database_connection(settings, psycopg)
    except RuntimeError as exc:
        print("ERROR: Production preflight failed.", file=sys.stderr)
        print(f"- {exc}", file=sys.stderr)
        return 2

    repository = PostgresQuestionBankRepository(
        connection
    )

    _save_manifest(manifest, work_root)

    print(f"ADR 022 — Production Batch Runner")
    print(f"PDFs to process: {total_to_run}")
    print(f"Work root: {work_root}")
    print(f"Resume: {args.resume}, Fail-fast: {args.fail_fast}")
    print()

    results: list[dict] = []
    start_time = time.monotonic()

    for i, entry in enumerate(to_process):
        paper_id = entry["paper_id"]
        pdf_path = Path(entry["pdf_path"])
        n = i + 1
        elapsed = time.monotonic() - start_time
        _print_progress(n, total_to_run, paper_id, elapsed)

        # Update manifest: running
        _update_manifest_entry(manifest, paper_id,
                               status="running",
                               started_at=datetime.now(timezone.utc).isoformat(),
                               attempts=entry["attempts"] + 1)
        _save_manifest(manifest, work_root)

        entry_prefix, entry_index = _split_manifest_paper_id(paper_id, prefix)
        result = _process_one_safe(
            pdf_path=pdf_path,
            index=entry_index,
            prefix=entry_prefix,
            work_root=work_root,
            asset_dir=args.asset_dir,
            resume=args.resume,
            deepseek_client=deepseek_client,
            mineru_command=settings.mineru_command,
            repository=repository,
        )

        # Update manifest
        run_report_path = str(Path(result["work_dir"]) / "run-report.json")
        _update_manifest_entry(manifest, paper_id,
                               status=result["status"],
                               finished_at=datetime.now(timezone.utc).isoformat(),
                               last_error=result["error"],
                               run_report_path=run_report_path)
        _save_manifest(manifest, work_root)

        results.append(result)

        if args.fail_fast and result["status"] in ("failed", "crashed"):
            print()
            print(f"Fail-fast: stopping after {paper_id} {result['status']}")
            break

    print()
    wall_elapsed = time.monotonic() - start_time

    # --- Post-processing ---
    # Step timing
    step_timings = _extract_step_timings(results)
    for st in step_timings:
        if wall_elapsed > 0:
            st["pct_of_wall"] = round(st["total_s"] / wall_elapsed * 100, 1)
        else:
            st["pct_of_wall"] = 0.0

    # Failure taxonomy
    failure_taxonomy: Counter[str] = Counter()
    failure_examples: dict[str, str] = {}
    for r in results:
        if r["error"]:
            cat = _classify_failure(r["error"])
            failure_taxonomy[cat] += 1
            if cat not in failure_examples:
                failure_examples[cat] = r["error"][:120]

    # Generate reports
    report_md = _generate_markdown_report(
        results, wall_elapsed, manifest, step_timings,
        failure_taxonomy, failure_examples,
    )
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / f"batch-{today}.md"
    md_path.write_text(report_md, encoding="utf-8")

    summary_json = _generate_json_summary(
        results, wall_elapsed, manifest, step_timings, failure_taxonomy,
    )
    json_path = work_root / f"batch-summary-{today}.json"
    json_path.write_text(json.dumps(summary_json, indent=2, ensure_ascii=False))

    # Print summary
    completed = sum(1 for r in results if r["status"] == "completed")
    partial = sum(1 for r in results if r["status"] == "partial")
    failed = sum(1 for r in results if r["status"] == "failed")
    crashed = sum(1 for r in results if r["status"] == "crashed")

    print(f"\nResults: {completed} completed, {partial} partial, "
          f"{failed} failed, {crashed} crashed (of {len(results)})")
    if total_to_run > 0:
        success_rate = (completed + partial) / total_to_run * 100
        print(f"Success rate: {success_rate:.1f}%")
    print(f"Report: {md_path}")
    print(f"Summary: {json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
