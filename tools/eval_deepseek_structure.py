"""ADR 014: Real DeepSeek structured small-batch evaluation tool.

Evaluates DeepSeek output structure quality using ADR 013 per-question gating.
Focused on "structuring quality" — not PDF splitting or MinerU accuracy.

Usage:
  python3 tools/eval_deepseek_structure.py --pdf-dir data/beta/pdf --limit 3
  python3 tools/eval_deepseek_structure.py --pdf-dir data/beta/pdf --limit 3 --resume
  python3 tools/eval_deepseek_structure.py --pdf-dir data/beta/pdf --no-dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Real DeepSeek structure quality evaluation (ADR 014)"
    )
    parser.add_argument(
        "--pdf-dir", type=Path, required=True,
        help="Directory containing PDF files to process")
    parser.add_argument(
        "--limit", type=int, default=3,
        help="Max number of PDFs to process (default: 3)")
    parser.add_argument(
        "--paper-prefix", type=str, default="deepseek_eval",
        help="Prefix for paper IDs (default: deepseek_eval)")
    parser.add_argument(
        "--work-root", type=Path, default=None,
        help="Root for per-paper work dirs (default: data/runs/deepseek_eval_<date>)")
    parser.add_argument(
        "--asset-dir", type=Path, default=Path("data/assets"),
        help="Asset storage directory (default: data/assets)")
    parser.add_argument(
        "--resume", action="store_true",
        help="Pass --resume to each paper's ingest-full invocation")
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Skip DB writes (default: True)")
    parser.add_argument(
        "--no-dry-run", action="store_false", dest="dry_run",
        help="Perform actual DB writes")
    parser.add_argument(
        "--report-dir", type=Path, default=Path("docs/eval"),
        help="Output directory for eval report (default: docs/eval)")
    return parser


# ---------------------------------------------------------------------------
# PDF page count (minimal heuristic, no PyPDF2 dependency)
# ---------------------------------------------------------------------------

_PAGE_RE = __import__("re").compile(rb'/Type\s*/\s*Page[^s]')


def count_pages(pdf_path: Path) -> int | None:
    try:
        data = pdf_path.read_bytes()
        matches = _PAGE_RE.findall(data)
        return len(matches) if matches else None
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Per-paper processing
# ---------------------------------------------------------------------------


def _process_one_pdf(
    pdf_path: Path,
    index: int,
    prefix: str,
    work_root: Path,
    asset_dir: Path,
    dry_run: bool,
    resume: bool,
    deepseek_client,
    mineru_command: str,
    repository=None,
) -> dict[str, Any]:
    """Run ingest_paper_full on a single PDF and extract quality stats."""
    paper_id = f"{prefix}_{index:04d}"
    work_dir = work_root / paper_id
    started = time.monotonic()

    # Lazy import — only import question_bank after arg validation
    from question_bank.services.paper_orchestrator import ingest_paper_full

    report = ingest_paper_full(
        paper_id=paper_id,
        pdf_path=str(pdf_path),
        work_dir=str(work_dir),
        asset_dir=str(asset_dir),
        dry_run=dry_run,
        resume=resume,
        repository=repository,
        deepseek_client=deepseek_client,
        mineru_command=mineru_command,
    )

    elapsed = time.monotonic() - started

    # Extract step-level data from report
    layout_q = 0
    deepseek_out = 0
    deepseek_status = "?"

    for s in report.steps:
        if s.name == "layout_ownership":
            layout_q = s.output_count
        if s.name == "deepseek_structure":
            deepseek_out = s.output_count
            deepseek_status = s.status

    error = _report_error_summary(report) if report.status == "failed" else None

    return {
        "paper_id": paper_id,
        "pdf_path": str(pdf_path),
        "work_dir": str(work_dir),
        "status": report.status,
        "layout_q": layout_q,
        "deepseek_out": deepseek_out,
        "deepseek_status": deepseek_status,
        "questions_passed": report.questions_passed,
        "questions_warning": report.questions_warning,
        "questions_failed": report.questions_failed,
        "failed_question_ids": report.failed_question_ids,
        "quality_warning_counts": report.quality_warning_counts,
        "elapsed_s": round(elapsed, 1),
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
    dry_run: bool,
    resume: bool,
    deepseek_client,
    mineru_command: str,
    repository=None,
) -> dict[str, Any]:
    """Wrap _process_one_pdf with failure isolation."""
    try:
        return _process_one_pdf(
            pdf_path, index, prefix, work_root, asset_dir,
            dry_run, resume, deepseek_client, mineru_command, repository,
        )
    except Exception as exc:
        return {
            "paper_id": f"{prefix}_{index:04d}",
            "pdf_path": str(pdf_path),
            "work_dir": str(work_root / f"{prefix}_{index:04d}"),
            "status": "failed",
            "layout_q": 0,
            "deepseek_out": 0,
            "deepseek_status": "CRASH",
            "questions_passed": 0,
            "questions_warning": 0,
            "questions_failed": 0,
            "failed_question_ids": [],
            "quality_warning_counts": {},
            "elapsed_s": 0,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _generate_markdown_report(results: list[dict], elapsed: float) -> str:
    """Generate ADR 014 evaluation markdown report."""
    today = datetime.now().strftime("%Y-%m-%d")
    total = len(results)

    total_passed = sum(r["questions_passed"] for r in results)
    total_warning = sum(r["questions_warning"] for r in results)
    total_failed = sum(r["questions_failed"] for r in results)
    total_questions = total_passed + total_warning + total_failed

    pipeline_failed = sum(1 for r in results if r["status"] == "failed")
    pipeline_completed = sum(1 for r in results if r["status"] == "completed")
    pipeline_partial = sum(1 for r in results if r["status"] == "partial")

    # Aggregate warning codes across all papers
    warning_counter: Counter[str] = Counter()
    for r in results:
        for code, count in r["quality_warning_counts"].items():
            warning_counter[code] += count

    # Build top failure reasons
    failure_reasons: Counter[str] = Counter()
    for r in results:
        if r["error"]:
            failure_reasons[_classify_error(r["error"])] += 1
        if r["status"] == "failed":
            failure_reasons["Pipeline step failure"] += 1

    lines: list[str] = []
    lines.append(f"# DeepSeek Structure Quality Evaluation — {today}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Total PDFs | {total} |")
    lines.append(f"| Pipeline completed | {pipeline_completed} |")
    lines.append(f"| Pipeline partial | {pipeline_partial} |")
    lines.append(f"| Pipeline failed | {pipeline_failed} |")
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

    # Per-paper results table
    lines.append("## Per-Paper Results")
    lines.append("")
    header = ("| Paper ID | Layout Q | Structured | Passed | Warning | Failed | "
              "Status | Elapsed |")
    sep = ("|----------|----------|------------|--------|---------|--------|"
           "--------|---------|")
    lines.append(header)
    lines.append(sep)
    for r in results:
        lines.append(
            f"| {r['paper_id']} | {r['layout_q']} | {r['deepseek_out']} | "
            f"{r['questions_passed']} | {r['questions_warning']} | "
            f"{r['questions_failed']} | {r['status']} | {r['elapsed_s']}s |"
        )
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

    # Failure reasons
    if failure_reasons:
        lines.append("## Top Failure Reasons")
        lines.append("")
        lines.append("| Reason | Count |")
        lines.append("|--------|-------|")
        for reason, count in failure_reasons.most_common():
            lines.append(f"| {reason} | {count} |")
        lines.append("")

    # Per-paper detail
    lines.append("## Per-Paper Detail")
    lines.append("")
    for r in results:
        paper_id = r["paper_id"]
        lines.append(f"### {paper_id}")
        lines.append("")
        if r["error"]:
            lines.append(f"**Crash**: {r['error'][:200]}")
            lines.append("")
            continue
        lines.append(f"- Status: {r['status']}")
        lines.append(f"- Layout questions: {r['layout_q']}")
        lines.append(f"- DeepSeek structured: {r['deepseek_out']}")
        lines.append(f"- Passed: {r['questions_passed']}")
        lines.append(f"- Warning: {r['questions_warning']}")
        lines.append(f"- Failed: {r['questions_failed']}")
        if r["failed_question_ids"]:
            lines.append(f"- Failed IDs: {', '.join(r['failed_question_ids'])}")
        if r["quality_warning_counts"]:
            lines.append(f"- Warning counts: {json.dumps(r['quality_warning_counts'], ensure_ascii=False)}")
        lines.append(f"- Elapsed: {r['elapsed_s']}s")
        lines.append(f"- Run report: `{r['work_dir']}/run-report.json`")
        lines.append("")

    # Conclusion
    lines.append("## Conclusion")
    lines.append("")
    _append_conclusion(lines, results, total_passed, total_warning, total_failed,
                       total_questions, pipeline_failed)
    lines.append("")

    return "\n".join(lines)


def _append_conclusion(
    lines: list[str],
    results: list[dict],
    total_passed: int,
    total_warning: int,
    total_failed: int,
    total_questions: int,
    pipeline_failed: int,
) -> None:
    """Compute and append PASS / CONDITIONAL / BLOCKED verdict."""
    has_failed_questions = total_failed > 0
    has_pipeline_failure = pipeline_failed > 0

    if total_questions == 0:
        lines.append("**BLOCKED** — No structured questions produced across any PDF.")
        return

    warning_ratio = total_warning / total_questions

    if has_failed_questions or has_pipeline_failure:
        lines.append("**BLOCKED** — One or more questions failed quality gating, "
                     "or one or more PDF pipelines failed.")
        lines.append("")
        lines.append("Must investigate before proceeding:")
        lines.append("- Review failed question IDs in the report above")
        lines.append("- Check DeepSeek response payloads for missing required fields")
        lines.append("- Verify that `stem_latex` is never empty in DeepSeek output")

        # Diagnosis hints
        all_warnings: Counter[str] = Counter()
        for r in results:
            for code, count in r["quality_warning_counts"].items():
                all_warnings[code] += count

        if all_warnings.get("answer_not_in_choices", 0) > total_questions * 0.3:
            lines.append("- `answer_not_in_choices` is dominant — "
                         "suspect DeepSeek prompt or choice parsing logic")
        if all_warnings.get("missing_analysis", 0) > total_questions * 0.3:
            lines.append("- `missing_analysis` is dominant — "
                         "suspect answer section extraction not matching question blocks")
        return

    if warning_ratio <= 0.3:
        lines.append(f"**PASS** — All {total_questions} questions passed quality gating "
                     f"with {total_warning} warnings ({warning_ratio:.1%} ≤ 30%). "
                     f"DeepSeek structure output is acceptable for full-batch ingestion.")
    else:
        lines.append(f"**CONDITIONAL** — No questions failed gating, but "
                     f"{total_warning} of {total_questions} questions have warnings "
                     f"({warning_ratio:.1%} > 30%).")
        lines.append("")
        lines.append("Recommended actions before full-batch ingestion:")
        lines.append("- Review the top warning codes above")
        lines.append("- If `answer_not_in_choices` is dominant, "
                     "check DeepSeek answer format vs choice label matching")
        lines.append("- If `missing_analysis` is dominant, "
                     "check whether answer section parsing covers all questions")


def _generate_json_summary(results: list[dict], elapsed: float) -> dict:
    """Generate ADR 014 JSON summary."""
    total_passed = sum(r["questions_passed"] for r in results)
    total_warning = sum(r["questions_warning"] for r in results)
    total_failed = sum(r["questions_failed"] for r in results)
    total_questions = total_passed + total_warning + total_failed

    all_warnings: Counter[str] = Counter()
    for r in results:
        for code, count in r["quality_warning_counts"].items():
            all_warnings[code] += count

    pipeline_failed = sum(1 for r in results if r["status"] == "failed")

    if total_questions == 0:
        verdict = "BLOCKED"
    elif total_failed > 0 or pipeline_failed > 0:
        verdict = "BLOCKED"
    elif total_warning / total_questions > 0.3:
        verdict = "CONDITIONAL"
    else:
        verdict = "PASS"

    return {
        "evaluation": "ADR 014 — Real DeepSeek Structure Quality",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_pdfs": len(results),
        "pipeline_completed": sum(1 for r in results if r["status"] == "completed"),
        "pipeline_partial": sum(1 for r in results if r["status"] == "partial"),
        "pipeline_failed": pipeline_failed,
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
        "elapsed_s": round(elapsed, 1),
        "verdict": verdict,
        "papers": [
            {
                "paper_id": r["paper_id"],
                "status": r["status"],
                "layout_q": r["layout_q"],
                "deepseek_out": r["deepseek_out"],
                "questions_passed": r["questions_passed"],
                "questions_warning": r["questions_warning"],
                "questions_failed": r["questions_failed"],
                "failed_question_ids": r["failed_question_ids"],
                "quality_warning_counts": r["quality_warning_counts"],
                "elapsed_s": r["elapsed_s"],
                "error": r["error"][:200] if r["error"] else None,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Error / warning classification
# ---------------------------------------------------------------------------


def _classify_error(error_text: str) -> str:
    if "mineru" in error_text.lower():
        return "MinerU: error"
    if "deepseek" in error_text.lower():
        return "DeepSeek: API error"
    if "layout" in error_text.lower():
        return "Layout Ownership: error"
    if "memory" in error_text.lower() or "timeout" in error_text.lower():
        return f"Resource: {error_text[:60]}"
    return f"Other: {error_text[:80]}"


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
    work_root = args.work_root or Path(f"data/runs/deepseek_eval_{today}")
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

    repository = None
    if not args.dry_run:
        try:
            import psycopg
            from question_bank.repository import PostgresQuestionBankRepository
        except ImportError:
            print("ERROR: psycopg is required with --no-dry-run.", file=sys.stderr)
            print("Install project dependencies first.", file=sys.stderr)
            return 2

        repository = PostgresQuestionBankRepository(
            psycopg.connect(psycopg_conninfo(settings.database_url))
        )

    print(f"ADR 014 — Real DeepSeek Structure Quality Evaluation")
    print(f"PDFs: {len(pdf_files)} from {pdf_dir}")
    print(f"Dry-run: {args.dry_run}, Resume: {args.resume}")
    print(f"Work root: {work_root}")
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
            dry_run=args.dry_run,
            resume=args.resume,
            deepseek_client=deepseek_client,
            mineru_command=settings.mineru_command,
            repository=repository,
        )
        results.append(result)

    print()  # newline after progress bar
    total_elapsed = time.monotonic() - start_time

    # Generate markdown report
    report_md = _generate_markdown_report(results, total_elapsed)
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / f"deepseek-structure-eval-{today}.md"
    md_path.write_text(report_md)

    # Generate JSON summary
    summary_json = _generate_json_summary(results, total_elapsed)
    json_path = work_root / f"deepseek-structure-summary-{today}.json"
    json_path.write_text(json.dumps(summary_json, indent=2, ensure_ascii=False))

    # Print summary
    total_passed = sum(r["questions_passed"] for r in results)
    total_warning = sum(r["questions_warning"] for r in results)
    total_failed = sum(r["questions_failed"] for r in results)
    total_questions = total_passed + total_warning + total_failed

    print(f"\nResults: {total_passed} passed, {total_warning} warning, "
          f"{total_failed} failed (of {total_questions} questions across "
          f"{len(results)} PDFs)")
    print(f"Report: {md_path}")
    print(f"Summary: {json_path}")

    verdict = summary_json["verdict"]
    print(f"Verdict: {verdict}")

    if verdict == "BLOCKED":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
