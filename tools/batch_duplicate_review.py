"""Generate duplicate candidate groups from MinerU output directories.

Read-only exporter: reads ADR 003 fingerprints, groups by collision,
outputs candidate groups with pairwise similarity scores.

Usage:
  python3 tools/batch_duplicate_review.py --input data/beta/mineru/
  python3 tools/batch_duplicate_review.py --input data/beta/mineru/ --out docs/eval/dup-candidates.json
  python3 tools/batch_duplicate_review.py --input data/beta/mineru/ --save-db
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def discover_paper_dirs(input_dir: Path) -> list[Path]:
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


def run_batch(
    input_dir: Path,
    *,
    fingerprint_type: str = "text",
    min_candidates: int = 2,
    max_items_per_group: int = 20,
    save_to_db: bool = False,
) -> list:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from question_bank.services.layout_ownership import layout_ownership
    from question_bank.services.question_identity import fingerprint_blocks
    from question_bank.services.duplicate_review import generate_candidate_groups

    entries = discover_paper_dirs(input_dir)
    identities_by_paper: dict[str, list] = {}

    for entry in entries:
        if not entry.is_dir():
            continue
        paper_id = entry.relative_to(input_dir).as_posix() if entry != input_dir else entry.name
        json_path = entry / "output.json"
        if not json_path.exists():
            print(f"  SKIP {paper_id}: missing output.json")
            continue

        raw = json.loads(json_path.read_text(encoding="utf-8"))
        try:
            blocks = layout_ownership(paper_id, raw)
            elements_by_id = _build_elements_by_id(raw)
            identities = fingerprint_blocks(paper_id, blocks, elements_by_id)
        except Exception as exc:
            print(f"  FAIL {paper_id}: {exc}")
            continue

        identities_by_paper[paper_id] = identities

    groups = generate_candidate_groups(
        identities_by_paper,
        min_candidates=min_candidates,
        max_items_per_group=max_items_per_group,
        fingerprint_type=fingerprint_type,
    )

    if save_to_db:
        _save_groups_to_db(groups)

    return groups


def _build_elements_by_id(raw_elements: list[dict]) -> dict:
    from question_bank.services.layout_ownership import _Element

    by_id: dict = {}
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


def _save_groups_to_db(groups: list) -> None:
    try:
        import psycopg
    except ImportError:
        print("psycopg is required for --save-db. Install project dependencies.", file=sys.stderr)
        return

    from question_bank.config import Settings, psycopg_conninfo
    from question_bank.repository import PostgresQuestionBankRepository

    settings = Settings.load()
    connection = psycopg.connect(psycopg_conninfo(settings.database_url))
    try:
        repo = PostgresQuestionBankRepository(connection)
        for group in groups:
            repo.save_duplicate_candidate_group(group)
        connection.commit()
        print(f"Saved {len(groups)} groups to database.")
    except Exception as exc:
        connection.rollback()
        print(f"Database save failed: {exc}", file=sys.stderr)
        raise


def format_groups_report(groups: list) -> str:
    from question_bank.services.duplicate_review import format_groups_summary

    summary = format_groups_summary(groups)

    # Per-group detail: top-3 items with pairwise similarity
    detail_lines: list[str] = []
    detail_lines.append("")
    detail_lines.append("  Group Details (top 10 groups)")
    detail_lines.append("  -----------------------------")

    for g in groups[:10]:
        detail_lines.append("")
        detail_lines.append(f"  [{g.id}] fingerprint={g.fingerprint}  items={len(g.items)}")
        detail_lines.append(f"  {'Item':<6} {'Paper':<30} {'Section':<30} {'Q#':>4}")
        detail_lines.append(f"  {'-'*6} {'-'*30} {'-'*30} {'-'*4}")

        for idx, item in enumerate(g.items[:5]):
            detail_lines.append(
                f"  {idx:<6} {item.paper_id:<30} {item.section_path:<30} "
                f"{item.question_number:>4}"
            )

        # Top pairwise similarities
        sorted_pairs = sorted(
            g.pairwise_similarities.items(), key=lambda x: -x[1].composite
        )[:3]
        if sorted_pairs:
            detail_lines.append("")
            detail_lines.append("  Top pairwise similarities:")
            for (i, j), s in sorted_pairs:
                detail_lines.append(
                    f"    [{i},{j}] text={s.text_match:.0f} latex={s.latex_match:.0f} "
                    f"asset={s.asset_match:.0f} section_jaccard={s.section_jaccard:.2f} "
                    f"composite={s.composite:.3f}"
                )

    return summary + "\n" + "\n".join(detail_lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate duplicate candidate groups from MinerU output directories."
    )
    parser.add_argument(
        "--input", type=Path, required=True,
        help="Directory containing paper subdirectories (each with output.json + output.md).",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Write JSON output to this file (prints summary to stdout if omitted).",
    )
    parser.add_argument(
        "--fp-type", default="text", choices=["text", "latex", "asset"],
        help="Fingerprint type for collision grouping (default: text).",
    )
    parser.add_argument(
        "--min-candidates", type=int, default=2,
        help="Minimum distinct papers per group (default: 2).",
    )
    parser.add_argument(
        "--max-items", type=int, default=20,
        help="Maximum items per group after trimming (default: 20).",
    )
    parser.add_argument(
        "--save-db", action="store_true",
        help="Persist candidate groups to PostgreSQL.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Input directory not found: {args.input}", file=sys.stderr)
        return 1

    groups = run_batch(
        args.input,
        fingerprint_type=args.fp_type,
        min_candidates=args.min_candidates,
        max_items_per_group=args.max_items,
        save_to_db=args.save_db,
    )

    if args.out:
        from question_bank.services.duplicate_review import groups_to_json

        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(groups_to_json(groups) + "\n", encoding="utf-8")
        print(f"JSON written to {args.out}")
        print(format_groups_report(groups))
    else:
        print(format_groups_report(groups))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
