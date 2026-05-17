"""Extract text blocks and images from a PDF into MinerU-compatible JSON + Markdown.

Uses PyMuPDF (fitz) to produce:
  - output.md: Markdown text in reading order (y -> x)
  - output.json: MinerU-style layout elements list

Usage:
  python tools/pdf_to_mineru.py <pdf_path> <output_dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def extract_from_pdf(pdf_path: Path, output_dir: Path) -> tuple[str, list[dict[str, Any]]]:
    import fitz

    doc = fitz.open(str(pdf_path))
    output_dir.mkdir(parents=True, exist_ok=True)
    image_dir = output_dir / "images"
    image_dir.mkdir(exist_ok=True)

    elements: list[dict[str, Any]] = []
    element_id = 0
    all_page_markdown: list[str] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_num = page_idx + 1
        page_w = page.rect.width
        page_h = page.rect.height

        # Use get_text("dict") for structured blocks with proper text/image distinction
        page_dict = page.get_text("dict")
        blocks = page_dict.get("blocks", [])

        page_spans: list[tuple[float, float, float, float, list[float], str]] = []

        for block in blocks:
            btype = block.get("type", 0)

            if btype == 1:  # Image block
                bbox_px = block["bbox"]
                x0, y0, x1, y1 = bbox_px
                bbox = [
                    round(max(0, x0 / page_w), 4),
                    round(max(0, y0 / page_h), 4),
                    round(min(1, x1 / page_w), 4),
                    round(min(1, y1 / page_h), 4),
                ]
                w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
                if w >= 0.01 and h >= 0.01:
                    element_id += 1
                    elements.append({
                        "id": f"e{element_id}",
                        "page": page_num,
                        "type": "image",
                        "bbox": bbox,
                        "text": "",
                    })

            elif btype == 0:  # Text block
                for line in block.get("lines", []):
                    line_bbox = line["bbox"]
                    # Collect spans within this line
                    line_text_parts: list[str] = []
                    for span in line.get("spans", []):
                        span_text = span["text"].strip()
                        if span_text:
                            line_text_parts.append(span_text)

                    if line_text_parts:
                        combined_text = "".join(line_text_parts)
                        lx0, ly0, lx1, ly1 = line_bbox
                        norm_bbox = [
                            round(max(0, lx0 / page_w), 4),
                            round(max(0, ly0 / page_h), 4),
                            round(min(1, lx1 / page_w), 4),
                            round(min(1, ly1 / page_h), 4),
                        ]
                        page_spans.append((ly0, lx0, ly1, lx1, norm_bbox, combined_text))

        # Sort by y then x (reading order)
        page_spans.sort(key=lambda s: (s[0], s[1]))

        # Collect page markdown
        page_md_lines: list[str] = []
        for _, _, _, _, bbox, text in page_spans:
            element_id += 1
            elem_type = "text"
            elements.append({
                "id": f"e{element_id}",
                "page": page_num,
                "type": elem_type,
                "bbox": bbox,
                "text": text,
            })
            page_md_lines.append(text)

        # Extract embedded images to files
        for img_index, img in enumerate(page.get_images(full=True)):
            xref = img[0]
            base_image = doc.extract_image(xref)
            if base_image is None:
                continue
            image_bytes = base_image.get("image")
            if image_bytes is None:
                continue
            ext = base_image.get("ext", "png")
            img_filename = f"p{page_num}_img{img_index + 1}.{ext}"
            img_path = image_dir / img_filename
            try:
                img_path.write_bytes(image_bytes)
            except OSError:
                continue

        if page_md_lines:
            all_page_markdown.append("\n".join(page_md_lines))
            all_page_markdown.append("")

    doc.close()

    markdown_text = "\n".join(all_page_markdown)
    return markdown_text, elements


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <pdf_path> <output_dir>", file=sys.stderr)
        return 1

    pdf_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2])

    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 1

    print(f"Extracting: {pdf_path.name}")
    markdown_text, elements = extract_from_pdf(pdf_path, output_dir)

    md_path = output_dir / "output.md"
    md_path.write_text(markdown_text, encoding="utf-8")
    print(f"  Markdown: {md_path} ({len(markdown_text)} chars)")

    json_path = output_dir / "output.json"
    json_path.write_text(json.dumps(elements, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Elements: {json_path} ({len(elements)} elements)")

    type_counts: dict[str, int] = {}
    for e in elements:
        type_counts[e["type"]] = type_counts.get(e["type"], 0) + 1
    print(f"  Types: {type_counts}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
