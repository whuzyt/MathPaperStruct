"""ADR 011: Non-dry-run asset linkage evaluation tool.

Runs ingest_paper_full() with dry_run=False against a real PostgreSQL database
to validate the full asset write path: identify → crop → store → phash → link.

Usage:
  python3 tools/eval_asset_linkage.py --pdf-dir data/beta/pdf --limit 3
  python3 tools/eval_asset_linkage.py --pdf-dir data/beta/pdf --limit 5 --resume
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Non-dry-run asset linkage evaluation (ADR 011)"
    )
    parser.add_argument(
        "--pdf-dir", type=Path, required=True,
        help="Directory containing PDF files to process")
    parser.add_argument(
        "--work-root", type=Path, default=None,
        help="Root for per-paper work dirs (default: data/runs/asset_eval_<date>)")
    parser.add_argument(
        "--asset-dir", type=Path, default=Path("data/assets"),
        help="Asset storage directory (default: data/assets)")
    parser.add_argument(
        "--limit", type=int, default=5,
        help="Max number of PDFs to process (default: 5)")
    parser.add_argument(
        "--resume", action="store_true",
        help="Pass --resume to each paper's ingest-full invocation")
    parser.add_argument(
        "--fail-fast", action="store_true",
        help="Stop on first failure instead of continuing")
    parser.add_argument(
        "--paper-prefix", type=str, default="asset_eval",
        help="Prefix for paper IDs to isolate evaluation runs (default: asset_eval)")
    parser.add_argument(
        "--db-url", type=str, default=None,
        help="PostgreSQL connection URL (default: from DATABASE_URL env)")
    parser.add_argument(
        "--report-dir", type=Path, default=Path("docs/eval"),
        help="Output directory for eval report (default: docs/eval)")
    return parser


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

_REQUIRED_TABLES = [
    "papers", "parse_runs", "question_blocks", "questions", "choices",
    "question_assets", "raw_assets", "question_asset_links",
]


def _check_schema(conn) -> list[str]:
    """Return list of missing required tables. Empty list means OK."""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
    )
    existing = {row[0] for row in cursor.fetchall()}
    missing = [t for t in _REQUIRED_TABLES if t not in existing]
    return missing


# ---------------------------------------------------------------------------
# MinerU element type counts
# ---------------------------------------------------------------------------

def _count_mineru_element_types(work_dir: Path, pdf_stem: str) -> dict[str, int]:
    """Count element types in MinerU content_list.json output."""
    json_candidates = sorted(work_dir.rglob(f"{pdf_stem}_content_list.json"))
    if not json_candidates:
        json_candidates = sorted(work_dir.rglob(f"{pdf_stem}_middle.json"))
    if not json_candidates:
        return {}

    try:
        data = json.loads(json_candidates[0].read_text())
        elements = data if isinstance(data, list) else data.get("elements", data.get("result", []))
        counts: Counter[str] = Counter()
        for e in elements:
            if isinstance(e, dict):
                counts[e.get("type", "unknown")] += 1
        return dict(counts)
    except (json.JSONDecodeError, OSError):
        return {}


def _visual_count(type_counts: dict[str, int]) -> int:
    """Sum of image, table, chart element counts."""
    return sum(type_counts.get(t, 0) for t in ("image", "table", "chart"))


# ---------------------------------------------------------------------------
# DB queries for supplementary metrics
# ---------------------------------------------------------------------------

def _query_asset_metrics(conn, paper_id: str) -> dict:
    """Query database for asset linkage metrics not in the orchestrator report."""
    cursor = conn.cursor()

    # raw_assets count
    cursor.execute(
        "SELECT COUNT(*) FROM raw_assets WHERE paper_id = %s", (paper_id,)
    )
    raw_assets_count = cursor.fetchone()[0]

    # question_asset_links count
    cursor.execute(
        "SELECT COUNT(*) FROM question_asset_links qal "
        "JOIN raw_assets ra ON qal.raw_asset_id = ra.id "
        "WHERE ra.paper_id = %s", (paper_id,)
    )
    links_count = cursor.fetchone()[0]

    # unassigned visual assets (raw_assets without any question link)
    cursor.execute(
        "SELECT COUNT(*) FROM raw_assets ra "
        "WHERE ra.paper_id = %s "
        "AND ra.asset_type IN ('image', 'table', 'chart') "
        "AND NOT EXISTS (SELECT 1 FROM question_asset_links qal "
        "                WHERE qal.raw_asset_id = ra.id)", (paper_id,)
    )
    unassigned_count = cursor.fetchone()[0]

    # low confidence assignments (confidence < 0.8)
    cursor.execute(
        "SELECT COUNT(*) FROM question_asset_links qal "
        "JOIN raw_assets ra ON qal.raw_asset_id = ra.id "
        "WHERE ra.paper_id = %s AND qal.confidence < 0.8", (paper_id,)
    )
    low_conf_count = cursor.fetchone()[0]

    return {
        "raw_assets": raw_assets_count,
        "links": links_count,
        "unassigned": unassigned_count,
        "low_confidence": low_conf_count,
    }


# ---------------------------------------------------------------------------
# PDF page count (minimal heuristic)
# ---------------------------------------------------------------------------

import re as _re

_PAGE_RE = _re.compile(rb'/Type\s*/\s*Page[^s]')

def _count_pages(pdf_path: Path) -> int | None:
    """Count pages in a PDF by scanning for /Type/Page entries."""
    try:
        data = pdf_path.read_bytes()
        matches = _PAGE_RE.findall(data)
        return len(matches) if matches else None
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _extract_step(report, step_name: str):
    """Return the first step with the given name, or None."""
    for s in report.steps:
        if s.name == step_name:
            return s
    return None


def _build_result_row(r: dict, db_metrics: dict | None) -> dict:
    """Build a flat result dict for a single paper."""
    error = r["error"]
    report = r["report"]
    mineru_types = r.get("mineru_types", {})

    if error:
        return {
            "paper_id": r["paper_id"],
            "pages": r.get("pages", "?"),
            "layout_q": 0,
            "mineru_visual": _visual_count(mineru_types),
            "raw_assets": 0,
            "links": 0,
            "crop_success": 0,
            "crop_failed": 0,
            "phash_success": 0,
            "unassigned": 0,
            "conflicts": 0,
            "low_confidence": 0,
            "warnings": 0,
            "errors": 1,
            "status": "failed",
            "run_report": str(r.get("work_dir", Path("."))) + "/run-report.json",
            "error_detail": error[:150],
        }

    layout_s = _extract_step(report, "layout_ownership")
    crop_s = _extract_step(report, "crop_assets")
    phash_s = _extract_step(report, "compute_phash")

    if crop_s and crop_s.status not in ("skipped",):
        crop_ok = crop_s.output_count
        crop_bad = len(crop_s.warnings) if crop_s.warnings else 0
    else:
        crop_ok = 0
        crop_bad = 0

    if phash_s and phash_s.status not in ("skipped",):
        phash_ok = phash_s.output_count
    else:
        phash_ok = 0

    db = db_metrics or {}

    return {
        "paper_id": r["paper_id"],
        "pages": r.get("pages", "?"),
        "layout_q": layout_s.output_count if layout_s else 0,
        "mineru_visual": _visual_count(mineru_types),
        "raw_assets": db.get("raw_assets", 0),
        "links": db.get("links", 0),
        "crop_success": crop_ok,
        "crop_failed": crop_bad,
        "phash_success": phash_ok,
        "unassigned": db.get("unassigned", 0),
        "conflicts": 0,  # v1: conflict tracking not yet implemented
        "low_confidence": db.get("low_confidence", 0),
        "warnings": len(report.warnings) if report else 0,
        "errors": len(report.errors) if report else 0,
        "status": report.status if report else "failed",
        "run_report": str(r.get("work_dir", Path("."))) + "/run-report.json",
        "error_detail": "",
    }


def _generate_report(results: list[dict], db_metrics_list: list[dict | None],
                     elapsed: float, args) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        _build_result_row(r, dbm)
        for r, dbm in zip(results, db_metrics_list)
    ]
    total = len(rows)

    completed = sum(1 for r in rows if r["status"] == "completed")
    partial = sum(1 for r in rows if r["status"] == "partial")
    failed = sum(1 for r in rows if r["status"] == "failed")
    crashed = sum(1 for r in results if r["error"])

    # Top failure reasons
    failure_reasons: Counter[str] = Counter()
    for r in results:
        if r["report"] and r["report"].errors:
            for e in r["report"].errors:
                failure_reasons[_classify_error(e)] += 1
        elif r["error"]:
            failure_reasons[_classify_error(r["error"])] += 1

    # Top warning patterns
    warning_patterns: Counter[str] = Counter()
    for r in results:
        if r["report"] and r["report"].warnings:
            for w in r["report"].warnings:
                warning_patterns[_classify_warning(w)] += 1

    lines: list[str] = []
    lines.append(f"# Asset Linkage Evaluation — {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total PDFs | {total} |")
    lines.append(f"| Completed | {completed} |")
    lines.append(f"| Partial | {partial} |")
    lines.append(f"| Failed | {failed} |")
    lines.append(f"| Crashed (unhandled) | {crashed} |")
    lines.append(f"| Success rate | {completed / total * 100:.1f}% |")
    lines.append(f"| Elapsed | {elapsed:.0f}s |")
    lines.append(f"| Avg per PDF | {elapsed / total:.1f}s |")
    lines.append(f"| Generated | {now} |")
    lines.append(f"| Paper prefix | {args.paper_prefix} |")
    lines.append("")

    # Asset-specific aggregate metrics
    total_visual = sum(r["mineru_visual"] for r in rows)
    total_raw = sum(r["raw_assets"] for r in rows)
    total_links = sum(r["links"] for r in rows)
    total_crop_ok = sum(r["crop_success"] for r in rows)
    total_crop_bad = sum(r["crop_failed"] for r in rows)
    total_phash = sum(r["phash_success"] for r in rows)
    total_unassigned = sum(r["unassigned"] for r in rows)
    total_low_conf = sum(r["low_confidence"] for r in rows)

    lines.append("## Asset Metrics (Aggregate)")
    lines.append("")
    lines.append(f"| Metric | Total |")
    lines.append(f"|--------|-------|")
    lines.append(f"| MinerU visual elements (image+table+chart) | {total_visual} |")
    lines.append(f"| raw_assets rows | {total_raw} |")
    lines.append(f"| question_asset_links | {total_links} |")
    lines.append(f"| Crop successes | {total_crop_ok} |")
    lines.append(f"| Crop failures | {total_crop_bad} |")
    lines.append(f"| pHash computed | {total_phash} |")
    lines.append(f"| Unassigned visual assets | {total_unassigned} |")
    lines.append(f"| Low-confidence links (<0.8) | {total_low_conf} |")
    lines.append("")

    lines.append("## Per-Paper Results")
    lines.append("")
    header = ("| Paper ID | Pages | Layout Q | M-Visual | RA | Links | "
              "Crop OK | Crop Fail | pHash | Unassgn | LowConf | "
              "Warn | Err | Status |")
    sep = ("|----------|-------|----------|----------|----|-------|"
           "---------|-----------|-------|---------|---------|"
           "------|-----|--------|")
    lines.append(header)
    lines.append(sep)
    for row in rows:
        lines.append(
            f"| {row['paper_id']} | {row['pages']} | {row['layout_q']} | "
            f"{row['mineru_visual']} | {row['raw_assets']} | {row['links']} | "
            f"{row['crop_success']} | {row['crop_failed']} | {row['phash_success']} | "
            f"{row['unassigned']} | {row['low_confidence']} | "
            f"{row['warnings']} | {row['errors']} | {row['status']} |"
        )
    lines.append("")

    if failure_reasons:
        lines.append("## Top Failure Reasons")
        lines.append("")
        lines.append("| Reason | Count |")
        lines.append("|--------|-------|")
        for reason, count in failure_reasons.most_common(10):
            lines.append(f"| {reason} | {count} |")
        lines.append("")

    if warning_patterns:
        lines.append("## Top Warning Patterns")
        lines.append("")
        lines.append("| Pattern | Count |")
        lines.append("|---------|-------|")
        for pattern, count in warning_patterns.most_common(10):
            lines.append(f"| {pattern} | {count} |")
        lines.append("")

    # Detailed per-paper section
    lines.append("## Per-Paper Detail")
    lines.append("")
    for i, r in enumerate(results):
        paper_id = r["paper_id"]
        lines.append(f"### {paper_id}")
        lines.append("")
        if r["error"]:
            lines.append(f"**Unhandled crash**: {r['error'][:200]}")
            lines.append("")
            continue
        report = r["report"]
        if not report:
            lines.append("No report generated.")
            lines.append("")
            continue

        # MinerU element type breakdown
        mineru_types = r.get("mineru_types", {})
        if mineru_types:
            type_str = ", ".join(f"{t}={c}" for t, c in sorted(mineru_types.items()))
            lines.append(f"MinerU elements: {type_str}")
            lines.append("")

        for s in report.steps:
            marker = {
                "success": "OK", "failed": "FAIL",
                "skipped": "SKIP", "warning": "WARN",
            }.get(s.status, s.status.upper())
            line = f"- [{marker}] {s.name} (in={s.input_count} out={s.output_count})"
            if s.error:
                line += f" — {s.error[:120]}"
            lines.append(line)
            for w in s.warnings:
                lines.append(f"  - WARNING: {w[:120]}")

        # DB metrics
        if i < len(db_metrics_list) and db_metrics_list[i]:
            dbm = db_metrics_list[i]
            lines.append(f"- DB: {dbm['raw_assets']} raw_assets, "
                         f"{dbm['links']} links, "
                         f"{dbm['unassigned']} unassigned visual, "
                         f"{dbm['low_confidence']} low-confidence")
        lines.append(f"- Run report: `{r['work_dir']}/run-report.json`")
        lines.append("")

    lines.append("## Conclusion")
    lines.append("")
    success_rate = completed / total * 100 if total else 0
    min_rate = 80.0

    papers_with_links = sum(1 for r in rows if r["links"] > 0)
    papers_with_visual = sum(1 for r in rows if r["mineru_visual"] > 0)

    crop_total = total_crop_ok + total_crop_bad
    crop_rate = total_crop_ok / crop_total * 100 if crop_total else 100

    phash_total = total_phash
    phash_rate = phash_total / total_raw * 100 if total_raw else 100

    issues: list[str] = []

    if success_rate < min_rate:
        issues.append(
            f"success rate {success_rate:.1f}% below {min_rate:.0f}% threshold")

    if papers_with_visual > 0 and papers_with_links == 0:
        issues.append(
            f"{papers_with_visual} papers have visual elements but 0 have links — "
            "identify_assets or link insertion may be broken")

    if papers_with_visual > 0 and total_raw == 0:
        issues.append(
            f"{papers_with_visual} papers have visual elements but raw_assets=0 — "
            "identify_raw_assets is not finding images")

    if crop_rate < 80:
        issues.append(f"crop success rate {crop_rate:.1f}% below 80%")

    if phash_rate < 80:
        issues.append(f"phash success rate {phash_rate:.1f}% below 80%")

    if total_unassigned > 0:
        issues.append(f"{total_unassigned} visual assets not linked to any question")

    if issues:
        lines.append(f"**BLOCKED** — {len(issues)} issue(s) found:")
        for issue in issues:
            lines.append(f"- {issue}")
    else:
        lines.append(
            f"**PASS** — {success_rate:.1f}% success rate, "
            f"{crop_rate:.1f}% crop success, "
            f"{phash_rate:.1f}% phash success. "
            f"Ready for small-batch DB ingestion."
        )
    lines.append("")

    return "\n".join(lines)


def _classify_error(error_text: str) -> str:
    if "mineru" in error_text.lower() or "MinerU" in error_text:
        return "MinerU: " + ("code 1" if "code 1" in error_text else "runtime error")
    if "layout" in error_text.lower():
        return "Layout Ownership: error"
    if "deepseek" in error_text.lower():
        return "DeepSeek: error"
    if "database" in error_text.lower() or "psycopg" in error_text.lower():
        return "Database: error"
    if "schema" in error_text.lower():
        return "Schema: missing tables"
    return f"Other: {error_text[:80]}"


def _classify_warning(warning_text: str) -> str:
    if "crop" in warning_text.lower():
        return "Crop: failure"
    if "phash" in warning_text.lower():
        return "pHash: computation failure"
    if "save" in warning_text.lower():
        return "Save: DB write"
    if "duplicate" in warning_text.lower():
        return "Duplicate: save failure"
    if "visual" in warning_text.lower():
        return "Visual: candidate generation"
    return f"Other: {warning_text[:80]}"


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

    if args.limit:
        pdf_files = pdf_files[:args.limit]

    today = datetime.now().strftime("%Y-%m-%d")
    work_root = args.work_root or Path(f"data/runs/asset_eval_{today}")
    work_root.mkdir(parents=True, exist_ok=True)

    # --- Database setup ---
    from question_bank.config import Settings, psycopg_conninfo

    settings = Settings.load()
    db_url = psycopg_conninfo(args.db_url or settings.database_url)

    try:
        import psycopg
    except ImportError:
        print("ERROR: psycopg is required for non-dry-run evaluation. "
              "Install with: pip install psycopg", file=sys.stderr)
        return 2

    try:
        conn = psycopg.connect(db_url)
    except Exception as exc:
        print(f"ERROR: Cannot connect to database: {exc}", file=sys.stderr)
        print(f"  URL: {db_url}", file=sys.stderr)
        print("  Ensure PostgreSQL is running (e.g. docker compose up -d postgres)", file=sys.stderr)
        return 2

    # Check schema
    missing = _check_schema(conn)
    if missing:
        print(f"ERROR: Missing database tables: {', '.join(missing)}", file=sys.stderr)
        print("  Run: question-bank db init", file=sys.stderr)
        conn.close()
        return 2

    conn.close()

    # Lazy imports after DB and arg validation
    from question_bank.services.deepseek import FakeDeepSeekClient
    from question_bank.services.paper_orchestrator import ingest_paper_full
    from question_bank.repository import PostgresQuestionBankRepository

    deepseek_client = FakeDeepSeekClient()

    print(f"Asset linkage eval: {len(pdf_files)} PDFs from {pdf_dir}")
    print(f"Work root: {work_root}")
    print(f"DB URL: {db_url.split('@')[-1] if '@' in db_url else db_url}")  # hide credentials
    print(f"Paper prefix: {args.paper_prefix}")
    print(f"Resume: {args.resume}, Fail-fast: {args.fail_fast}")
    print()

    results: list[dict] = []
    db_metrics_list: list[dict | None] = []
    start_time = time.monotonic()

    for i, pdf_path in enumerate(pdf_files):
        paper_id = f"{args.paper_prefix}_{pdf_path.stem}"
        work_dir = work_root / paper_id
        n = i + 1
        total = len(pdf_files)

        # Progress bar
        bar_width = 30
        filled = int(bar_width * n / total)
        bar = "█" * filled + "░" * (bar_width - filled)
        elapsed_i = time.monotonic() - start_time
        eta = (elapsed_i / n * (total - n)) if n > 0 else 0
        print(f"\r  [{bar}] {n}/{total} | {paper_id:<30} | "
              f"elapsed={elapsed_i:.0f}s eta={eta:.0f}s", end="", flush=True)

        pages = _count_pages(pdf_path)

        # Create fresh DB connection per paper (avoid stale connection issues)
        try:
            conn = psycopg.connect(db_url)
            repository = PostgresQuestionBankRepository(conn)
        except Exception as exc:
            results.append({
                "paper_id": paper_id,
                "pages": pages or "?",
                "work_dir": str(work_dir),
                "mineru_types": {},
                "report": None,
                "error": f"DB connection failed: {exc}",
            })
            db_metrics_list.append(None)
            if args.fail_fast:
                print()
                break
            continue

        report = None
        try:
            report = ingest_paper_full(
                paper_id=paper_id,
                pdf_path=str(pdf_path),
                work_dir=str(work_dir),
                asset_dir=str(args.asset_dir),
                dry_run=False,
                resume=args.resume,
                repository=repository,
                deepseek_client=deepseek_client,
                mineru_command=settings.mineru_command,
            )

            # Query DB for supplementary asset metrics
            try:
                db_metrics = _query_asset_metrics(conn, paper_id)
            except Exception:
                db_metrics = None
            db_metrics_list.append(db_metrics)

            # Read MinerU element types
            mineru_types = _count_mineru_element_types(work_dir, pdf_path.stem)

            results.append({
                "paper_id": paper_id,
                "pages": pages or "?",
                "work_dir": str(work_dir),
                "mineru_types": mineru_types,
                "report": report,
                "error": None,
            })
        except Exception as exc:
            results.append({
                "paper_id": paper_id,
                "pages": pages or "?",
                "work_dir": str(work_dir),
                "mineru_types": {},
                "report": report,
                "error": str(exc),
            })
            db_metrics_list.append(None)
            if args.fail_fast:
                conn.close()
                print()
                break
        finally:
            conn.close()

    print()  # newline after progress bar
    elapsed = time.monotonic() - start_time

    # Generate report
    report_content = _generate_report(results, db_metrics_list, elapsed, args)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"asset-linkage-eval-{today}.md"
    report_path.write_text(report_content)

    # Generate JSON summary
    json_path = work_root / f"asset-linkage-summary-{today}.json"

    rows_for_json = [
        {
            "paper_id": r["paper_id"],
            "status": r["report"].status if r["report"] else "crashed",
            "error": r["error"][:200] if r["error"] else None,
            "work_dir": r["work_dir"],
            "mineru_types": r.get("mineru_types", {}),
        }
        for r in results
    ]
    json_path.write_text(json.dumps({
        "total": len(results),
        "completed": sum(1 for r in results if r["report"] and r["report"].status == "completed"),
        "partial": sum(1 for r in results if r["report"] and r["report"].status == "partial"),
        "failed": sum(1 for r in results if r["report"] and r["report"].status == "failed"),
        "crashed": sum(1 for r in results if r["error"]),
        "elapsed_s": elapsed,
        "paper_prefix": args.paper_prefix,
        "papers": rows_for_json,
    }, indent=2, ensure_ascii=False))

    # Print summary
    total = len(results)
    completed = sum(1 for r in results if r["report"] and r["report"].status == "completed")
    partial = sum(1 for r in results if r["report"] and r["report"].status == "partial")
    failed = sum(1 for r in results if r["report"] and r["report"].status == "failed")
    crashed = sum(1 for r in results if r["error"])

    print(f"\nResults: {completed} completed, {partial} partial, "
          f"{failed} failed, {crashed} crashed (of {total})")
    print(f"Report: {report_path}")
    print(f"JSON:   {json_path}")

    success_rate = completed / total * 100 if total else 0
    if success_rate >= 80:
        print(f"Verdict: PASS ({success_rate:.1f}% >= 80%)")
        return 0
    else:
        print(f"Verdict: BLOCKED ({success_rate:.1f}% < 80%)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
