"""Run layout_ownership shadow comparison over a directory of MinerU outputs.

Usage:
  python3 tools/batch_shadow.py --input data/beta/mineru/
  python3 tools/batch_shadow.py --input data/beta/mineru/ --out docs/eval/beta-shadow-2026-05-17.md
  python3 tools/batch_shadow.py --input data/eval/paper_g4          # single paper
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


# ---------------------------------------------------------------------------
# Paper stratification: classify by layout characteristics
# ---------------------------------------------------------------------------

def classify_paper(paper_id: str, raw_elements: list[dict]) -> str:
    """Heuristic classification into one of the 5 strata."""
    from question_bank.services.layout_ownership import ALT_SECTION_PATTERN

    x_centers: list[float] = []
    image_count = 0
    has_nonstandard = False
    has_answer_section = False
    page_count = 1

    for e in raw_elements:
        bbox = e.get("bbox", [])
        if len(bbox) == 4 and e.get("type") in ("text", "formula"):
            x_centers.append((bbox[0] + bbox[2]) / 2)
        if e.get("type") == "image":
            image_count += 1
        text = e.get("text", "").strip()
        page_count = max(page_count, e.get("page", 1))
        if ALT_SECTION_PATTERN.match(text):
            has_nonstandard = True
        if "参考答案" in text or "答案与解析" in text:
            has_answer_section = True

    total = len(raw_elements)
    image_ratio = image_count / total if total else 0

    # Column detection: single-col ~0.15, two-col ~0.25+
    if x_centers:
        mean_x = sum(x_centers) / len(x_centers)
        x_std = (sum((x - mean_x) ** 2 for x in x_centers) / len(x_centers)) ** 0.5
        x_range = max(x_centers) - min(x_centers)
    else:
        x_std = 0
        x_range = 0

    is_two_column = x_std > 0.22

    # Classify in order of specificity
    if has_nonstandard:
        return "nonstandard_section"
    if is_two_column:
        return "two_column"
    if image_ratio > 0.15:
        return "figure_heavy"
    if page_count >= 10 or has_answer_section:
        return "cross_page"
    return "single_column"


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def discover_paper_dirs(input_dir: Path) -> list[Path]:
    """Return dirs that directly contain a MinerU output.json + output.md pair."""
    if input_dir.is_file():
        return []
    if (input_dir / "output.json").exists() and (input_dir / "output.md").exists():
        return [input_dir]

    paper_dirs = {
        path.parent
        for path in input_dir.rglob("output.json")
        if (path.parent / "output.md").exists()
    }
    return sorted(paper_dirs, key=lambda p: p.relative_to(input_dir).as_posix())


def _build_elements_by_id(raw_elements: list[dict]) -> "dict[str, _Element]":
    from question_bank.services.layout_ownership import _Element

    by_id: dict[str, _Element] = {}
    for e in raw_elements:
        eid = e.get("id")
        if not eid:
            continue
        bbox = e.get("bbox", [])
        if len(bbox) != 4:
            continue
        x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
        by_id[str(eid)] = _Element(
            id=str(eid),
            page=int(e.get("page", 1)),
            type=str(e.get("type", "")),
            bbox=(x1, y1, x2, y2),
            text=str(e.get("text", "") or ""),
            confidence=float(e.get("confidence", 1.0) or 1.0),
        )
    return by_id


def _compute_intra_paper_collisions(
    identities: list,
) -> int:
    """Count blocks sharing a non-empty text_fingerprint within the same paper."""
    from collections import Counter

    fps = [i.text_fingerprint for i in identities if i.text_fingerprint]
    if not fps:
        return 0
    counts = Counter(fps)
    return sum(c - 1 for c in counts.values() if c > 1)


def run_batch(input_dir: Path) -> dict[str, dict]:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from question_bank.services.layout_ownership import layout_ownership
    from question_bank.services.question_identity import fingerprint_blocks
    from question_bank.services.question_splitter import split_markdown_into_blocks
    from question_bank.services.shadow_comparator import compare

    results: dict[str, dict] = {}
    entries = discover_paper_dirs(input_dir)

    for entry in entries:
        if not entry.is_dir():
            continue
        paper_id = entry.relative_to(input_dir).as_posix() if entry != input_dir else entry.name
        json_path = entry / "output.json"
        md_path = entry / "output.md"
        if not json_path.exists() or not md_path.exists():
            print(f"  SKIP {paper_id}: missing output.json or output.md")
            continue

        raw = json.loads(json_path.read_text(encoding="utf-8"))
        md = md_path.read_text(encoding="utf-8")

        try:
            old = split_markdown_into_blocks(paper_id, md)
            new = layout_ownership(paper_id, raw)
            report = compare(paper_id, old, new)

            elements_by_id = _build_elements_by_id(raw)
            identities = fingerprint_blocks(paper_id, new, elements_by_id)
            intra_dup = _compute_intra_paper_collisions(identities)
        except Exception as exc:
            print(f"  FAIL {paper_id}: {exc}")
            results[paper_id] = {"error": str(exc)}
            continue

        stratum = classify_paper(paper_id, raw)
        results[paper_id] = {
            "old_count": report.old_question_count,
            "new_count": report.new_question_count,
            "matched": len(report.matched_numbers),
            "old_only": len(report.old_only_numbers),
            "new_only": len(report.new_only_numbers),
            "warning_counts": dict(report.warning_counts),
            "total_warnings": report.total_warnings,
            "section_hierarchy_suspected": report.warning_counts.get(
                "section_hierarchy_suspected", 0
            ),
            "assets": report.asset_assignment_count,
            "low_conf_assets": report.low_confidence_asset_count,
            "stratum": stratum,
            "identities": identities,
            "intra_paper_dup_candidates": intra_dup,
        }

    return results


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def format_batch_report(results: dict[str, dict], title: str = "Beta Shadow Batch Report") -> str:
    papers = list(results)
    total = len(papers)
    if total == 0:
        return "No papers to report."

    sh_papers = sum(
        1 for r in results.values()
        if r.get("section_hierarchy_suspected", 0) > 0
    )
    sh_rate = sh_papers / total * 100 if total else 0

    # Stratum breakdown
    strata: dict[str, dict] = {}
    stratum_order = ["single_column", "two_column", "figure_heavy", "cross_page", "nonstandard_section"]
    stratum_labels = {
        "single_column": "单栏普通卷",
        "two_column": "双栏普通卷",
        "figure_heavy": "图文/几何题多",
        "cross_page": "跨页解答题",
        "nonstandard_section": "非标准 section/专题/题组",
    }
    for paper, r in sorted(results.items()):
        s = r.get("stratum", "unknown")
        if s not in strata:
            strata[s] = {"count": 0, "sh_count": 0, "total_old": 0, "total_new": 0}
        strata[s]["count"] += 1
        if r.get("section_hierarchy_suspected", 0) > 0:
            strata[s]["sh_count"] += 1
        if "error" not in r:
            strata[s]["total_old"] += r["old_count"]
            strata[s]["total_new"] += r["new_count"]

    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"  {title} — {total} papers")
    lines.append("=" * 72)
    lines.append("")

    # Per-paper table
    lines.append(f"  {'Paper':<28} {'Old':>4} {'New':>4} {'Match':>5} {'Warn':>5} {'SH':>4} {'DupCand':>7} {'Assets':>6}  Stratum")
    lines.append(f"  {'-'*28} {'-'*4} {'-'*4} {'-'*5} {'-'*5} {'-'*4} {'-'*7} {'-'*6}  {'-'*20}")

    for paper, r in sorted(results.items()):
        if "error" in r:
            lines.append(f"  {paper:<28} ERROR: {r['error']}")
            continue
        s = stratum_labels.get(r.get("stratum", ""), r.get("stratum", ""))
        intra_dup = r.get("intra_paper_dup_candidates", 0)
        lines.append(
            f"  {paper:<28} {r['old_count']:>4} {r['new_count']:>4} "
            f"{r['matched']:>5} {r['total_warnings']:>5} "
            f"{r['section_hierarchy_suspected']:>4} {intra_dup:>7} {r['assets']:>6}  {s}"
        )

    # Stratum breakdown
    lines.append("")
    lines.append("  Stratum Breakdown")
    lines.append("  ----------------")
    lines.append(f"  {'Stratum':<25} {'Papers':>6} {'SH':>4} {'SH%':>5} {'Old Q':>6} {'New Q':>6}")
    lines.append(f"  {'-'*25} {'-'*6} {'-'*4} {'-'*5} {'-'*6} {'-'*6}")
    for s in stratum_order:
        if s not in strata:
            continue
        d = strata[s]
        label = stratum_labels.get(s, s)
        s_sh_rate = d["sh_count"] / d["count"] * 100 if d["count"] else 0
        lines.append(
            f"  {label:<25} {d['count']:>6} {d['sh_count']:>4} {s_sh_rate:>4.0f}% "
            f"{d['total_old']:>6} {d['total_new']:>6}"
        )

    # Summary
    lines.append("")
    lines.append("  Summary")
    lines.append("  -------")
    lines.append(f"  Total papers                      : {total}")
    lines.append(f"  section_hierarchy_suspected papers : {sh_papers} ({sh_rate:.0f}%)")

    agg_warnings: dict[str, int] = {}
    total_warnings = 0
    total_old = 0
    total_new = 0
    for r in results.values():
        if "error" in r:
            continue
        total_old += r["old_count"]
        total_new += r["new_count"]
        total_warnings += r["total_warnings"]
        for code, count in r["warning_counts"].items():
            agg_warnings[code] = agg_warnings.get(code, 0) + count

    lines.append(f"  Total old splitter questions      : {total_old}")
    lines.append(f"  Total layout_ownership questions   : {total_new}")
    lines.append(f"  Total warnings                    : {total_warnings}")
    lines.append("")

    if agg_warnings:
        lines.append("  Aggregated Warning Counts:")
        for code, count in sorted(agg_warnings.items(), key=lambda x: -x[1]):
            lines.append(f"    {code}: {count}")
        lines.append("")

    # Cross-paper identity collisions
    from collections import Counter

    fp_to_papers: dict[str, set[str]] = {}
    for paper, r in results.items():
        if "error" in r:
            continue
        for ident in r.get("identities", []):
            fp = ident.text_fingerprint
            if fp:
                fp_to_papers.setdefault(fp, set()).add(paper)

    cross_paper_collisions = {
        fp: papers for fp, papers in fp_to_papers.items() if len(papers) >= 2
    }
    lines.append("  Cross-Paper Identity Collisions")
    lines.append("  -------------------------------")
    lines.append(f"  Unique text fingerprints         : {len(fp_to_papers)}")
    lines.append(f"  Fingerprints appearing in ≥2 papers: {len(cross_paper_collisions)}")
    lines.append("")

    if cross_paper_collisions:
        top_collisions = sorted(
            cross_paper_collisions.items(), key=lambda x: -len(x[1])
        )[:10]
        lines.append(f"  {'Rank':<6} {'Fingerprint':<18} {'Papers':>7}  Papers")
        lines.append(f"  {'-'*6} {'-'*18} {'-'*7}  {'-'*20}")
        for rank, (fp, papers) in enumerate(top_collisions, 1):
            paper_list = ", ".join(sorted(papers)[:5])
            if len(papers) > 5:
                paper_list += f", ... (+{len(papers) - 5})"
            lines.append(f"  {rank:<6} {fp:<18} {len(papers):>7}  {paper_list}")
        lines.append("")

    lines.append("=" * 72)

    # Quality gate assessment
    lines.append("")
    lines.append("  Quality Gate Assessment")
    lines.append("  -----------------------")
    checks = [
        ("section_hierarchy_suspected ≤ 20%", sh_rate <= 20, f"{sh_rate:.0f}%"),
        ("Total papers ≥ 30", total >= 30, str(total)),
        ("Two-column papers ≥ 8", strata.get("two_column", {}).get("count", 0) >= 8,
         str(strata.get("two_column", {}).get("count", 0))),
        ("Nonstandard-section papers ≥ 5", strata.get("nonstandard_section", {}).get("count", 0) >= 5,
         str(strata.get("nonstandard_section", {}).get("count", 0))),
    ]
    for label, passed, value in checks:
        status = "✓ PASS" if passed else "✗ FAIL"
        lines.append(f"  {label}: {status} ({value})")

    lines.append("")
    if sh_rate > 20:
        lines.append("  → section_hierarchy_suspected exceeds 20%. Pause batch expansion,")
        lines.append("    implement ADR 002, re-evaluate.")

    return "\n".join(lines)


def print_batch_report(results: dict[str, dict]) -> None:
    print(format_batch_report(results))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run layout_ownership shadow comparison on MinerU output directories."
    )
    parser.add_argument(
        "--input", type=Path, required=True,
        help="Directory containing paper subdirectories (each with output.json + output.md).",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Write markdown report to this file (prints to stdout if omitted).",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Input directory not found: {args.input}", file=sys.stderr)
        return 1

    results = run_batch(args.input)

    report_text = format_batch_report(results)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report_text + "\n", encoding="utf-8")
        print(f"Report written to {args.out}")
    else:
        print(report_text)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
