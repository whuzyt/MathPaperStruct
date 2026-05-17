"""ADR 010: Batch dry-run paper ingestion evaluation tool.

Usage:
  python3 tools/batch_ingest_full.py --pdf-dir data/beta/pdf --limit 10
  python3 tools/batch_ingest_full.py --pdf-dir data/beta/pdf --limit 10 --resume
  python3 tools/batch_ingest_full.py --pdf-dir data/beta/pdf --fail-fast --limit 5
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Batch dry-run paper ingestion evaluation (ADR 010)"
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
        "--limit", type=int, default=10,
        help="Max number of PDFs to process (default: 10)")
    parser.add_argument(
        "--resume", action="store_true",
        help="Pass --resume to each paper's ingest-full invocation")
    parser.add_argument(
        "--fail-fast", action="store_true",
        help="Stop on first failure instead of continuing")
    parser.add_argument(
        "--report-dir", type=Path, default=Path("docs/eval"),
        help="Output directory for eval report (default: docs/eval)")
    return parser


# ---------------------------------------------------------------------------
# PDF page count — minimal heuristic, no PyPDF2 dependency
# ---------------------------------------------------------------------------

_PAGE_RE = re.compile(rb'/Type\s*/\s*Page[^s]')

def count_pages(pdf_path: Path) -> int | None:
    """Count pages in a PDF by scanning for /Type/Page entries."""
    try:
        data = pdf_path.read_bytes()
        matches = _PAGE_RE.findall(data)
        return len(matches) if matches else None
    except OSError:
        return None


def _page_count_from_work_dir(work_dir: Path, pdf_stem: str) -> int | None:
    """Extract max page number from MinerU content_list.json elements."""
    json_candidates = sorted(work_dir.rglob(f"{pdf_stem}_content_list.json"))
    if not json_candidates:
        json_candidates = sorted(work_dir.rglob(f"{pdf_stem}_middle.json"))
    if not json_candidates:
        return None
    try:
        data = json.loads(json_candidates[0].read_text())
        elements = data if isinstance(data, list) else data.get("elements", data.get("result", []))
        if not elements:
            return None
        pages = {e.get("page", 0) for e in elements if isinstance(e, dict)}
        return max(pages) if pages else None
    except (json.JSONDecodeError, OSError, KeyError):
        return None


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _extract_step(report, step_name: str) -> dict | None:
    for s in report.steps:
        if s.name == step_name:
            return s
    return None


def _build_result_row(r: dict) -> dict:
    """Build a flat result dict from an ingestion result entry."""
    error = r["error"]
    report = r["report"]

    work_dir = Path(r.get("work_dir", "."))

    if error:
        return {
            "paper_id": r["paper_id"],
            "pages": r.get("pages", "?"),
            "mineru": "CRASH",
            "layout_in": 0,
            "layout_q": 0,
            "deepseek_out": 0,
            "warnings": 0,
            "errors": 1,
            "status": "failed",
            "run_report": str(work_dir / "run-report.json"),
            "error_detail": error[:120],
        }

    mineru_s = _extract_step(report, "mineru_parse")
    layout_s = _extract_step(report, "layout_ownership")
    deepseek_s = _extract_step(report, "deepseek_structure")

    return {
        "paper_id": r["paper_id"],
        "pages": r.get("pages", "?"),
        "mineru": mineru_s.status if mineru_s else "?",
        "layout_in": layout_s.input_count if layout_s else 0,
        "layout_q": layout_s.output_count if layout_s else 0,
        "deepseek_out": deepseek_s.output_count if deepseek_s else 0,
        "warnings": len(report.warnings) if report else 0,
        "errors": len(report.errors) if report else 0,
        "status": report.status if report else "failed",
        "run_report": str(work_dir / "run-report.json"),
        "error_detail": "",
    }


def _generate_report(results: list[dict], elapsed: float, args) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(results)
    rows = [_build_result_row(r) for r in results]

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
    lines.append(f"# Batch Ingestion Evaluation — {datetime.now().strftime('%Y-%m-%d')}")
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
    lines.append("")

    lines.append("## Per-Paper Results")
    lines.append("")
    header = ("| Paper ID | Pages | MinerU | Layout In | Layout Q | "
              "DeepSeek Out | Warnings | Errors | Status |")
    sep = "|----------|-------|--------|-----------|----------|"
    sep += "-------------|----------|--------|--------|"
    lines.append(header)
    lines.append(sep)
    for row in rows:
        lines.append(
            f"| {row['paper_id']} | {row['pages']} | {row['mineru']} | "
            f"{row['layout_in']} | {row['layout_q']} | {row['deepseek_out']} | "
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
    for r in results:
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
        for s in report.steps:
            marker = {"success": "OK", "failed": "FAIL", "skipped": "SKIP", "warning": "WARN"}.get(
                s.status, s.status.upper())
            line = f"- [{marker}] {s.name} (in={s.input_count} out={s.output_count})"
            if s.error:
                line += f" — {s.error[:120]}"
            lines.append(line)
            for w in s.warnings:
                lines.append(f"  - WARNING: {w[:120]}")
        lines.append(f"- Run report: `{r['work_dir']}/run-report.json`")
        lines.append("")

    lines.append("## Conclusion")
    lines.append("")
    success_rate = completed / total * 100 if total else 0
    min_rate = 80.0
    if success_rate >= min_rate:
        lines.append(f"**PASS** — {success_rate:.1f}% success rate meets the {min_rate:.0f}% threshold. "
                     f"The main pipeline is stable for continued development.")
    else:
        lines.append(f"**BLOCKED** — {success_rate:.1f}% success rate below the {min_rate:.0f}% threshold. "
                     f"Top failures must be investigated before proceeding to the next ADR.")
    lines.append("")

    return "\n".join(lines)


def _classify_error(error_text: str) -> str:
    """Classify an error message into a short category."""
    if "mineru" in error_text.lower() or "MinerU" in error_text:
        if "code 1" in error_text:
            return "MinerU: exited with code 1"
        if "not found" in error_text.lower():
            return "MinerU: command not found"
        return "MinerU: runtime error"
    if "layout" in error_text.lower():
        return "Layout Ownership: error"
    if "deepseek" in error_text.lower():
        return "DeepSeek: error"
    if "database" in error_text.lower() or "psycopg" in error_text.lower():
        return "Database: connection error"
    if "memory" in error_text.lower() or "timeout" in error_text.lower():
        return f"Resource: {error_text[:60]}"
    return f"Other: {error_text[:80]}"


def _classify_warning(warning_text: str) -> str:
    """Classify a warning message into a short category."""
    if "crop" in warning_text.lower():
        return "Crop: partial failure"
    if "save" in warning_text.lower() or "duplicate" in warning_text.lower():
        return "Duplicate: save failure"
    if "visual" in warning_text.lower():
        return "Visual: candidate generation"
    if "phash" in warning_text.lower():
        return "pHash: computation"
    if "asset" in warning_text.lower():
        return "Asset: identification"
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
    work_root = args.work_root or Path(f"data/runs/batch_{today}")
    work_root.mkdir(parents=True, exist_ok=True)

    # Lazy imports — only import question_bank after arg validation
    from question_bank.config import Settings
    from question_bank.services.deepseek import FakeDeepSeekClient
    from question_bank.services.paper_orchestrator import ingest_paper_full

    settings = Settings.load()
    deepseek_client = FakeDeepSeekClient()

    print(f"Batch ingest: {len(pdf_files)} PDFs from {pdf_dir}")
    print(f"Work root: {work_root}")
    print(f"Resume: {args.resume}, Fail-fast: {args.fail_fast}")
    print()

    results: list[dict] = []
    start_time = time.monotonic()

    for i, pdf_path in enumerate(pdf_files):
        paper_id = pdf_path.stem
        work_dir = work_root / paper_id
        n = i + 1
        total = len(pdf_files)

        # Progress bar: [#####     ] 3/10
        bar_width = 30
        filled = int(bar_width * n / total)
        bar = "█" * filled + "░" * (bar_width - filled)
        elapsed_i = time.monotonic() - start_time
        eta = (elapsed_i / n * (total - n)) if n > 0 else 0
        print(f"\r  [{bar}] {n}/{total} | {paper_id:<20} | "
              f"elapsed={elapsed_i:.0f}s eta={eta:.0f}s", end="", flush=True)

        pages = count_pages(pdf_path)

        try:
            report = ingest_paper_full(
                paper_id=paper_id,
                pdf_path=str(pdf_path),
                work_dir=str(work_dir),
                asset_dir=str(args.asset_dir),
                dry_run=True,
                resume=args.resume,
                repository=None,
                deepseek_client=deepseek_client,
                mineru_command=settings.mineru_command,
            )
            # Try to get page count from MinerU output if PDF heuristic failed
            if pages is None:
                pages = _page_count_from_work_dir(work_dir, paper_id)

            results.append({
                "paper_id": paper_id,
                "pdf_path": str(pdf_path),
                "pages": pages or "?",
                "work_dir": str(work_dir),
                "report": report,
                "error": None,
            })
        except Exception as exc:
            results.append({
                "paper_id": paper_id,
                "pdf_path": str(pdf_path),
                "pages": pages or "?",
                "work_dir": str(work_dir),
                "report": None,
                "error": str(exc),
            })
            if args.fail_fast:
                print()
                break

    print()  # newline after progress bar
    elapsed = time.monotonic() - start_time

    # Generate report
    report_content = _generate_report(results, elapsed, args)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"ingest-full-batch-{today}.md"
    report_path.write_text(report_content)

    # Generate per-paper summary JSON for tooling
    summary_path = work_root / f"batch-summary-{today}.json"
    summary_path.write_text(json.dumps({
        "total": len(results),
        "completed": sum(1 for r in results if r["report"] and r["report"].status == "completed"),
        "partial": sum(1 for r in results if r["report"] and r["report"].status == "partial"),
        "failed": sum(1 for r in results if r["report"] and r["report"].status == "failed"),
        "crashed": sum(1 for r in results if r["error"]),
        "elapsed_s": elapsed,
        "papers": [
            {
                "paper_id": r["paper_id"],
                "status": r["report"].status if r["report"] else "crashed",
                "error": r["error"][:200] if r["error"] else None,
                "work_dir": r["work_dir"],
            }
            for r in results
        ],
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
    print(f"Summary: {summary_path}")

    success_rate = completed / total * 100 if total else 0
    if success_rate >= 80:
        print(f"Verdict: PASS ({success_rate:.1f}% >= 80%)")
        return 0
    else:
        print(f"Verdict: BLOCKED ({success_rate:.1f}% < 80%)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
