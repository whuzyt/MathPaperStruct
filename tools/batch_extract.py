"""Batch extract PDFs to MinerU-compatible JSON + Markdown.

Usage:
  python3 tools/batch_extract.py data/beta/pdf/ data/beta/mineru/
"""

from __future__ import annotations

import sys
import time
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <pdf_dir> <output_dir>", file=sys.stderr)
        return 1

    pdf_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    from pdf_to_mineru import extract_from_pdf

    pdfs = sorted(pdf_dir.glob("*.pdf"))
    total = len(pdfs)
    if total == 0:
        print(f"No PDFs found in {pdf_dir}", file=sys.stderr)
        return 1

    print(f"Processing {total} PDFs...")
    t0 = time.monotonic()
    ok = 0
    fail = 0

    for i, pdf_path in enumerate(pdfs):
        paper_id = pdf_path.stem
        paper_dir = output_dir / paper_id
        try:
            md, elements = extract_from_pdf(pdf_path, paper_dir)
            md_path = paper_dir / "output.md"
            md_path.write_text(md, encoding="utf-8")

            import json
            json_path = paper_dir / "output.json"
            json_path.write_text(
                json.dumps(elements, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            ok += 1
            if (i + 1) % 10 == 0 or i == total - 1:
                elapsed = time.monotonic() - t0
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                print(f"  [{i+1}/{total}] {elapsed:.0f}s ({rate:.1f} papers/s) — last: {paper_id}")
        except Exception as exc:
            fail += 1
            print(f"  FAIL {paper_id}: {exc}")

    elapsed = time.monotonic() - t0
    print(f"\nDone: {ok} ok, {fail} fail in {elapsed:.1f}s")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
