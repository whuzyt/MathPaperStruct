from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TextIO

from question_bank.config import Settings
from question_bank.ingestion import PDFIngestionError, PDFIngestionService
from question_bank.pipeline import ProcessingPipeline, ProcessingResult
from question_bank.repository import PostgresQuestionBankRepository
from question_bank.services.deepseek import DeepSeekHTTPClient, FakeDeepSeekClient
from question_bank.services.mineru import LocalMinerURunner
from question_bank.services.layout_ownership import layout_ownership
from question_bank.services.question_splitter import split_markdown_into_blocks
from question_bank.services.shadow_comparator import compare, format_report


def main(
    argv: list[str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "ingest":
        return _run_ingest(args, stdout, stderr)
    if args.command == "db" and args.db_command == "init":
        return _run_db_init(stdout, stderr)
    if args.command == "review" and args.review_command == "list":
        return _run_review_list(args, stdout, stderr)
    if args.command == "review" and args.review_command == "duplicate":
        if args.duplicate_command == "generate":
            return _run_duplicate_generate(args, stdout, stderr)
        if args.duplicate_command == "list":
            return _run_duplicate_list(args, stdout, stderr)
        if args.duplicate_command == "decide":
            return _run_duplicate_decide(args, stdout, stderr)
    if args.command == "review" and args.review_command == "canonicalize":
        if args.canon_command == "generate":
            return _run_canonicalize_generate(args, stdout, stderr)
        if args.canon_command == "list":
            return _run_canonicalize_list(args, stdout, stderr)
        if args.canon_command == "rollback":
            return _run_canonicalize_rollback(args, stdout, stderr)
    if args.command == "review" and args.review_command == "asset":
        if args.asset_command == "generate":
            return _run_asset_generate(args, stdout, stderr)
        if args.asset_command == "list":
            return _run_asset_list(args, stdout, stderr)

    parser.print_help(stdout)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="question-bank")
    subparsers = parser.add_subparsers(dest="command")

    ingest = subparsers.add_parser("ingest", help="Ingest one PDF or MinerU Markdown artifact.")
    ingest.add_argument("--paper-id", required=True)
    source = ingest.add_mutually_exclusive_group(required=True)
    source.add_argument("--pdf", type=Path)
    source.add_argument("--from-markdown", type=Path)
    ingest.add_argument("--output-dir", type=Path)
    ingest.add_argument("--dry-run", action="store_true", help="Process without saving to database.")
    ingest.add_argument("--save-db", action="store_true", help="Persist results to PostgreSQL.")
    ingest.add_argument("--use-real-deepseek", action="store_true")
    ingest.add_argument("--enable-layout-ownership", action="store_true",
                        help="Run layout_ownership in shadow mode and print comparison report.")
    ingest.add_argument("--layout-elements", type=Path,
                        help="Path to MinerU JSON elements file for shadow comparison (markdown mode).")

    db = subparsers.add_parser("db", help="Database utilities.")
    db_subparsers = db.add_subparsers(dest="db_command")
    db_subparsers.add_parser("init", help="Initialize PostgreSQL schema.")

    review = subparsers.add_parser("review", help="Review queue utilities.")
    review_subparsers = review.add_subparsers(dest="review_command")
    review_list = review_subparsers.add_parser("list", help="List questions that need review.")
    review_list.add_argument("--limit", type=int, default=50)

    # review duplicate
    duplicate = review_subparsers.add_parser("duplicate", help="Duplicate candidate review.")
    dup_subparsers = duplicate.add_subparsers(dest="duplicate_command")

    dup_generate = dup_subparsers.add_parser(
        "generate", help="Generate duplicate candidate groups from fingerprint collisions."
    )
    dup_generate.add_argument("--paper-dir", type=Path, required=True)
    dup_generate.add_argument("--fp-type", default="text", choices=["text", "latex", "asset"])
    dup_generate.add_argument("--min-candidates", type=int, default=2)
    dup_generate.add_argument("--max-items", type=int, default=20)
    dup_generate.add_argument("--save-db", action="store_true")
    dup_generate.add_argument("--out", type=Path)

    dup_list = dup_subparsers.add_parser("list", help="List duplicate candidate groups.")
    dup_list.add_argument("--status", default=None)
    dup_list.add_argument("--group-id")
    dup_list.add_argument("--limit", type=int, default=50)

    dup_decide = dup_subparsers.add_parser("decide", help="Record a review decision.")
    dup_decide.add_argument("--group-id", required=True)
    dup_decide.add_argument("--decision", required=True,
                            choices=["same", "variant", "unrelated", "unsure"])
    dup_decide.add_argument("--canonical-question-id", default=None)
    dup_decide.add_argument("--reviewer", default="")
    dup_decide.add_argument("--reason", default="")

    # review canonicalize
    canon = review_subparsers.add_parser(
        "canonicalize", help="Generate canonical question from resolved group."
    )
    canon_sub = canon.add_subparsers(dest="canon_command")
    canon_gen = canon_sub.add_parser("generate", help="Generate canonical question.")
    canon_gen.add_argument("--group-id", required=True)
    canon_gen.add_argument("--created-by", required=True)
    canon_list = canon_sub.add_parser("list", help="List canonical questions.")
    canon_list.add_argument("--status", default=None)
    canon_list.add_argument("--canonical-id")
    canon_list.add_argument("--limit", type=int, default=50)
    canon_rollback = canon_sub.add_parser("rollback", help="Rollback a canonical question.")
    canon_rollback.add_argument("--canonical-id", required=True)
    canon_rollback.add_argument("--created-by", required=True)

    # review asset
    asset = review_subparsers.add_parser("asset", help="Asset identity and canonicalization.")
    asset_sub = asset.add_subparsers(dest="asset_command")

    asset_gen = asset_sub.add_parser("generate", help="Generate raw assets from paper.")
    asset_gen.add_argument("--paper-id", required=True)
    asset_gen.add_argument("--elements-json", type=Path, required=True,
                           help="Path to MinerU output.json")

    asset_list = asset_sub.add_parser("list", help="List raw assets or canonical candidates.")
    asset_list.add_argument("--paper-id", default=None)
    asset_list.add_argument("--canonical", action="store_true",
                            help="List canonical asset candidates instead of raw assets.")
    asset_list.add_argument("--limit", type=int, default=100)

    return parser


def _run_ingest(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    settings = Settings.load()
    try:
        deepseek_client = _build_deepseek_client(args.use_real_deepseek, settings)
        repository = _build_repository(args.save_db)
        original_markdown: str | None = None

        if args.from_markdown is not None:
            original_markdown = _read_markdown(args.from_markdown)
            pipeline = ProcessingPipeline(deepseek_client=deepseek_client)
            if args.save_db:
                result = pipeline.process_and_save_markdown(
                    args.paper_id, original_markdown, repository
                )
            else:
                result = pipeline.process_markdown(args.paper_id, original_markdown)
        else:
            output_dir = args.output_dir or Path("data/mineru") / args.paper_id
            service = PDFIngestionService(
                mineru_runner=LocalMinerURunner(command=settings.mineru_command),
                deepseek_client=deepseek_client,
                repository=repository,
            )
            result = service.ingest_pdf(args.paper_id, args.pdf, output_dir)
            # Read original markdown for shadow comparison
            md_path = output_dir / "output.md"
            if md_path.exists():
                original_markdown = md_path.read_text(encoding="utf-8").strip()

        _print_summary(result, stdout)

        # Shadow comparison: layout_ownership vs old splitter
        # Enabled via CLI flag or ENABLE_LAYOUT_OWNERSHIP env var
        enable_lo = args.enable_layout_ownership or settings.enable_layout_ownership
        if enable_lo and original_markdown is not None:
            _run_shadow_comparison(args, original_markdown, stdout, stderr)
        elif enable_lo:
            print(
                "layout-ownership shadow: no markdown available for comparison.",
                file=stderr,
            )

        return 0
    except (PDFIngestionError, ValueError, RuntimeError, OSError) as exc:
        print(str(exc), file=stderr)
        return 2


def _run_shadow_comparison(
    args: argparse.Namespace,
    original_markdown: str,
    stdout: TextIO,
    stderr: TextIO,
) -> None:
    """Run layout_ownership alongside the old splitter and print a comparison report.

    The old-splitter baseline always uses `original_markdown` — the raw MinerU
    output file content — never reconstructed text from pipeline blocks. This
    ensures the comparison is not skewed by the old splitter's own decisions.
    """
    # Get MinerU JSON elements
    elements_path: Path | None = None
    if args.layout_elements is not None:
        elements_path = args.layout_elements
    elif args.output_dir is not None:
        default_json = args.output_dir / "output.json"
        if default_json.exists():
            elements_path = default_json
    elif args.pdf is not None:
        # Try the default output dir
        output_dir = args.output_dir or Path("data/mineru") / args.paper_id
        candidate = output_dir / "output.json"
        if candidate.exists():
            elements_path = candidate

    if elements_path is None:
        print(
            "layout-ownership shadow: no MinerU JSON elements found. "
            "Use --layout-elements to provide a JSON file, or run in PDF mode.",
            file=stderr,
        )
        return

    try:
        import json
        raw_elements = json.loads(elements_path.read_text(encoding="utf-8"))
        if not isinstance(raw_elements, list):
            print("layout-ownership shadow: JSON must be a list of elements.", file=stderr)
            return
    except Exception as exc:
        print(f"layout-ownership shadow: failed to read elements JSON: {exc}", file=stderr)
        return

    # Run old splitter
    old_blocks = split_markdown_into_blocks(args.paper_id, original_markdown)

    # Run layout_ownership
    try:
        new_blocks = layout_ownership(args.paper_id, raw_elements)
    except Exception as exc:
        print(f"layout-ownership shadow: layout_ownership raised: {exc}", file=stderr)
        return

    # Compare and print report
    report = compare(args.paper_id, old_blocks, new_blocks)
    print(format_report(report), file=stdout)


def _build_deepseek_client(use_real_deepseek: bool, settings: Settings):
    if not use_real_deepseek:
        return FakeDeepSeekClient()
    if settings.deepseek_api_key is None:
        raise ValueError("DEEPSEEK_API_KEY is required when --use-real-deepseek is set.")
    return DeepSeekHTTPClient(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
    )


def _build_repository(save_db: bool):
    if not save_db:
        return NullRepository()
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("psycopg is required when --save-db is set. Install project dependencies.") from exc

    settings = Settings.load()
    connection = psycopg.connect(settings.database_url)
    return PostgresQuestionBankRepository(connection)


def _run_db_init(stdout: TextIO, stderr: TextIO) -> int:
    try:
        import psycopg
    except ImportError:
        print("psycopg is required for `question-bank db init`. Install project dependencies.", file=stderr)
        return 2

    settings = Settings.load()
    connection = psycopg.connect(settings.database_url)
    cursor = connection.cursor()
    try:
        for schema_path in _schema_paths():
            schema_sql = schema_path.read_text(encoding="utf-8")
            cursor.execute(schema_sql)
        connection.commit()
    except Exception as exc:
        connection.rollback()
        print(f"schema initialization failed: {exc}", file=stderr)
        return 2

    print(f"schema initialized ({len(_schema_paths())} files)", file=stdout)
    return 0


def _run_review_list(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    try:
        import psycopg
    except ImportError:
        print("psycopg is required for `question-bank review list`. Install project dependencies.", file=stderr)
        return 2

    settings = Settings.load()
    repository = PostgresQuestionBankRepository(psycopg.connect(settings.database_url))
    for item in repository.list_review_queue(limit=args.limit):
        errors = ",".join(item.error_codes) or "-"
        warnings = ",".join(item.model_warnings) or "-"
        stem_preview = item.stem_latex.replace("\n", " ")[:40]
        print(
            (
                f"{item.question_id}\t{item.question_type}\t"
                f"score={item.overall_score:.2f}\terrors={errors}\t"
                f"warnings={warnings}\t{stem_preview}"
            ),
            file=stdout,
        )
    return 0


def _run_duplicate_generate(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    if not args.paper_dir.exists():
        print(f"Directory not found: {args.paper_dir}", file=stderr)
        return 2

    from question_bank.services.duplicate_review import (
        DuplicateCandidateGroup,
        format_groups_summary,
        generate_candidate_groups,
        groups_to_json,
    )
    from tools.batch_duplicate_review import run_batch

    groups = run_batch(
        args.paper_dir,
        fingerprint_type=args.fp_type,
        min_candidates=args.min_candidates,
        max_items_per_group=args.max_items,
        save_to_db=args.save_db,
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(groups_to_json(groups) + "\n", encoding="utf-8")
        print(f"JSON written to {args.out}", file=stdout)

    print(format_groups_summary(groups), file=stdout)
    return 0


def _run_duplicate_list(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    try:
        import psycopg
    except ImportError:
        print("psycopg is required. Install project dependencies.", file=stderr)
        return 2

    settings = Settings.load()
    repository = PostgresQuestionBankRepository(psycopg.connect(settings.database_url))

    if args.group_id:
        group = repository.get_duplicate_group(args.group_id)
        if group is None:
            print(f"Group not found: {args.group_id}", file=stderr)
            return 2
        import json as _json
        print(_json.dumps(group, ensure_ascii=False, indent=2), file=stdout)
        return 0

    groups = repository.list_duplicate_groups(status=args.status, limit=args.limit)
    for g in groups:
        print(
            f"{g['id']}\t{g['fingerprint_type']}\t"
            f"count={g['candidate_count']}\t"
            f"max_sim={g['max_similarity']:.3f}\t"
            f"status={g['status']}",
            file=stdout,
        )
    return 0


def _run_duplicate_decide(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    try:
        import psycopg
    except ImportError:
        print("psycopg is required. Install project dependencies.", file=stderr)
        return 2

    from question_bank.services.duplicate_review import ReviewDecision

    settings = Settings.load()
    repository = PostgresQuestionBankRepository(psycopg.connect(settings.database_url))

    decision = ReviewDecision(
        group_id=args.group_id,
        decision=args.decision,
        canonical_question_id=args.canonical_question_id,
        reviewer=args.reviewer,
        reason=args.reason,
    )
    repository.save_review_decision(decision)
    print(f"Decision recorded: group={args.group_id} decision={args.decision}", file=stdout)
    return 0


def _run_canonicalize_generate(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    try:
        import psycopg
    except ImportError:
        print("psycopg is required. Install project dependencies.", file=stderr)
        return 2

    settings = Settings.load()
    repository = PostgresQuestionBankRepository(psycopg.connect(settings.database_url))
    try:
        result = repository.canonicalize_group(args.group_id, args.created_by)
    except ValueError as exc:
        print(str(exc), file=stderr)
        return 2

    cq = result["canonical"]
    variants = result["variants"]
    event = result.get("event")

    print(f"Canonical question: {cq['id']}", file=stdout)
    print(f"  Representative: {cq['representative_item_id']}", file=stdout)
    print(f"  Status: {cq['status']}", file=stdout)
    print(f"  Variants: {len(variants)}", file=stdout)
    if event:
        print(f"  Event: {event['event_type']}", file=stdout)
    for v in variants:
        print(f"    - {v['paper_id']} #{v['source_position_key']}", file=stdout)
    return 0


def _run_canonicalize_list(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    try:
        import psycopg
    except ImportError:
        print("psycopg is required. Install project dependencies.", file=stderr)
        return 2

    settings = Settings.load()
    repository = PostgresQuestionBankRepository(psycopg.connect(settings.database_url))

    if args.canonical_id:
        cq = repository.get_canonical_question(args.canonical_id)
        if cq is None:
            print(f"Canonical question not found: {args.canonical_id}", file=stderr)
            return 2
        import json as _json
        print(_json.dumps(cq, ensure_ascii=False, indent=2), file=stdout)
        return 0

    questions = repository.list_canonical_questions(
        status=args.status, limit=args.limit
    )
    for cq in questions:
        print(
            f"{cq['id']}\t{cq['status']}\t"
            f"rep={cq['representative_item_id']}\t"
            f"group={cq['created_from_group_id']}",
            file=stdout,
        )
    return 0


def _run_canonicalize_rollback(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    try:
        import psycopg
    except ImportError:
        print("psycopg is required. Install project dependencies.", file=stderr)
        return 2

    settings = Settings.load()
    repository = PostgresQuestionBankRepository(psycopg.connect(settings.database_url))
    try:
        repository.rollback_canonical(args.canonical_id, args.created_by)
    except Exception as exc:
        print(f"Rollback failed: {exc}", file=stderr)
        return 2

    print(f"Canonical question rolled back: {args.canonical_id}", file=stdout)
    return 0


def _run_asset_generate(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    import json as _json

    try:
        import psycopg
    except ImportError:
        print("psycopg is required. Install project dependencies.", file=stderr)
        return 2

    if not args.elements_json.exists():
        print(f"Elements JSON not found: {args.elements_json}", file=stderr)
        return 2

    raw_elements = _json.loads(args.elements_json.read_text(encoding="utf-8"))

    from question_bank.services.asset_identity import _Element
    from question_bank.services.layout_ownership import layout_ownership

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

    blocks = layout_ownership(args.paper_id, raw_elements)

    settings = Settings.load()
    repository = PostgresQuestionBankRepository(psycopg.connect(settings.database_url))
    try:
        result = repository.identify_paper_assets(args.paper_id, blocks, elements_by_id)
    except Exception as exc:
        print(f"Asset generation failed: {exc}", file=stderr)
        return 2

    print(f"Raw assets: {len(result['raw_assets'])}", file=stdout)
    print(f"Question-asset links: {len(result['links'])}", file=stdout)
    for ra in result["raw_assets"]:
        print(
            f"  {ra['id']}\ttype={ra['asset_type']}\thash={ra['content_hash']}",
            file=stdout,
        )
    return 0


def _run_asset_list(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    try:
        import psycopg
    except ImportError:
        print("psycopg is required. Install project dependencies.", file=stderr)
        return 2

    settings = Settings.load()
    repository = PostgresQuestionBankRepository(psycopg.connect(settings.database_url))

    if args.canonical:
        candidates = repository.list_asset_candidates()
        for c in candidates:
            ca = c["canonical"]
            variants = c["variants"]
            print(
                f"{ca['id']}\ttype={ca['asset_type']}\t"
                f"content_hash={ca['content_hash']}\tvariants={len(variants)}",
                file=stdout,
            )
        return 0

    raw_assets = repository.list_raw_assets(paper_id=args.paper_id, limit=args.limit)
    for ra in raw_assets:
        print(
            f"{ra['id']}\tpaper={ra['paper_id']}\t"
            f"type={ra['asset_type']}\thash={ra['content_hash']}",
            file=stdout,
        )
    return 0


def _schema_paths() -> list[Path]:
    db_dir = Path(__file__).resolve().parents[2] / "db"
    return sorted(db_dir.glob("*.sql"))


def _read_markdown(markdown_path: Path) -> str:
    if not markdown_path.exists():
        raise FileNotFoundError(f"Markdown file does not exist: {markdown_path}")
    markdown = markdown_path.read_text(encoding="utf-8").strip()
    if not markdown:
        raise RuntimeError(f"Markdown file is empty: {markdown_path}")
    return markdown


def _print_summary(result: ProcessingResult, stdout: TextIO) -> None:
    needs_review = sum(report.needs_review for report in result.quality_reports)
    print(
        (
            f"paper_id={result.paper_id} "
            f"blocks={len(result.blocks)} "
            f"questions={len(result.questions)} "
            f"needs_review={needs_review}"
        ),
        file=stdout,
    )


class NullRepository:
    def save_processing_result(self, result: ProcessingResult) -> None:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
