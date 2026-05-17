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
    schema_sql = _schema_path().read_text(encoding="utf-8")
    connection = psycopg.connect(settings.database_url)
    cursor = connection.cursor()
    try:
        cursor.execute(schema_sql)
        connection.commit()
    except Exception as exc:
        connection.rollback()
        print(f"schema initialization failed: {exc}", file=stderr)
        return 2

    print("schema initialized", file=stdout)
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


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[2] / "db" / "001_initial_schema.sql"


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
