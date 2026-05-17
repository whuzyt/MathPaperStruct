from __future__ import annotations

from dataclasses import dataclass, field

from question_bank.domain.models import QuestionBlock
from question_bank.services.layout_ownership import LayoutOwnershipBlock


@dataclass(slots=True)
class ShadowComparisonReport:
    paper_id: str
    # counts
    old_question_count: int
    new_question_count: int
    # warning summary from layout_ownership
    warning_counts: dict[str, int]
    total_warnings: int
    # asset summary from layout_ownership
    asset_assignment_count: int
    low_confidence_asset_count: int
    # mismatch detail (first 10)
    old_only_numbers: list[str]
    new_only_numbers: list[str]
    matched_numbers: list[str]


def compare(
    paper_id: str,
    old_blocks: list[QuestionBlock],
    new_blocks: list[LayoutOwnershipBlock],
) -> ShadowComparisonReport:
    """Compare old splitter output against layout_ownership output.

    Runs in shadow mode — does not modify any state.
    """
    old_numbers = {b.question_number for b in old_blocks}
    new_numbers = {b.question_number for b in new_blocks}

    matched = sorted(old_numbers & new_numbers, key=_natural_key)
    old_only = sorted(old_numbers - new_numbers, key=_natural_key)
    new_only = sorted(new_numbers - old_numbers, key=_natural_key)

    # Warning counts from layout_ownership
    warning_counts: dict[str, int] = {}
    total_warnings = 0
    for b in new_blocks:
        for w in b.warnings:
            code = w.split(":")[0].strip() if ":" in w else w.strip()
            warning_counts[code] = warning_counts.get(code, 0) + 1
            total_warnings += 1

    # Asset summary
    asset_count = 0
    low_conf_asset_count = 0
    for b in new_blocks:
        for a in b.assets:
            asset_count += 1
            if a.needs_review:
                low_conf_asset_count += 1

    return ShadowComparisonReport(
        paper_id=paper_id,
        old_question_count=len(old_blocks),
        new_question_count=len(new_blocks),
        warning_counts=warning_counts,
        total_warnings=total_warnings,
        asset_assignment_count=asset_count,
        low_confidence_asset_count=low_conf_asset_count,
        old_only_numbers=old_only[:10],
        new_only_numbers=new_only[:10],
        matched_numbers=matched,
    )


def format_report(report: ShadowComparisonReport) -> str:
    """Format a human-readable shadow comparison report."""
    lines: list[str] = []
    lines.append("=" * 62)
    lines.append(f"  Layout Ownership Shadow Comparison — {report.paper_id}")
    lines.append("=" * 62)
    lines.append("")
    lines.append(f"  old splitter question_count : {report.old_question_count}")
    lines.append(f"  layout ownership question_count : {report.new_question_count}")
    lines.append(f"  matched                        : {len(report.matched_numbers)}")
    lines.append(f"  only in old splitter           : {len(report.old_only_numbers)}")
    lines.append(f"  only in layout_ownership       : {len(report.new_only_numbers)}")
    lines.append("")

    if report.total_warnings > 0:
        lines.append(f"  layout ownership warnings (total: {report.total_warnings}):")
        for code, count in sorted(report.warning_counts.items()):
            lines.append(f"    {code}: {count}")
    else:
        lines.append("  layout ownership warnings: none")
    lines.append("")

    lines.append(f"  assets assigned        : {report.asset_assignment_count}")
    lines.append(f"  low-confidence assets  : {report.low_confidence_asset_count}")
    lines.append("")

    if report.old_only_numbers:
        lines.append(f"  only in old splitter ({len(report.old_only_numbers)}):")
        lines.append(f"    {', '.join(report.old_only_numbers[:10])}")
    if report.new_only_numbers:
        lines.append(f"  only in layout_ownership ({len(report.new_only_numbers)}):")
        lines.append(f"    {', '.join(report.new_only_numbers[:10])}")
    if not report.old_only_numbers and not report.new_only_numbers:
        lines.append("  All question numbers match.")
    lines.append("")
    lines.append("=" * 62)

    return "\n".join(lines)


def _natural_key(s: str) -> tuple[int, str]:
    try:
        return (int(s), "")
    except ValueError:
        return (0, s)
