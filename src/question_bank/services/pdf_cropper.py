"""ADR 007: PDF Crop v1 — Crop image/table/figure regions from PDF pages.

Uses PyMuPDF (fitz) to render PDF pages and extract asset regions.
Single-crop failure does not abort the batch. content_hash is SHA256 of
the cropped PNG bytes, replacing the structural hash from ADR 006.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


@dataclass(slots=True)
class CropResult:
    raw_asset_id: str
    page: int
    bbox: tuple[float, float, float, float]
    crop_path: str | None
    content_hash: str
    width: int | None
    height: int | None
    error: str | None


def crop_pdf_assets(
    pdf_path: str,
    raw_assets: list[dict],
    output_dir: str,
    *,
    dpi: int = 300,
) -> list[CropResult]:
    try:
        import fitz  # type: ignore[import-untyped]
    except ImportError:
        raise ImportError(
            "PyMuPDF (fitz) is required for PDF cropping. "
            "Install it with: pip install PyMuPDF"
        )

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    os.makedirs(output_dir, exist_ok=True)
    zoom = dpi / 72.0
    results: list[CropResult] = []

    doc = fitz.open(pdf_path)
    try:
        for ra in raw_assets:
            ra_id = ra.get("id", "")
            page_num = ra.get("page", 1)
            bbox_json = ra.get("bbox_json", "[0,0,0,0]")

            # Parse bbox
            if isinstance(bbox_json, str):
                import json as _json
                bbox = tuple(_json.loads(bbox_json))
            else:
                bbox = tuple(bbox_json)

            # Validate page
            page_index = page_num - 1
            if page_index < 0 or page_index >= len(doc):
                results.append(CropResult(
                    raw_asset_id=ra_id, page=page_num, bbox=bbox,
                    crop_path=None, content_hash="", width=None, height=None,
                    error=f"Page {page_num} out of range (1-{len(doc)})",
                ))
                continue

            # Validate bbox
            x1, y1, x2, y2 = bbox
            if x2 <= x1 or y2 <= y1:
                results.append(CropResult(
                    raw_asset_id=ra_id, page=page_num, bbox=bbox,
                    crop_path=None, content_hash="", width=None, height=None,
                    error=f"Invalid bbox: zero or negative area {bbox}",
                ))
                continue

            try:
                page = doc[page_index]
                page_rect = page.rect
                pw, ph = page_rect.width, page_rect.height

                # Convert normalized bbox to pixel coords, clamped to page
                px1 = max(0, min(int(x1 * pw), int(pw)))
                py1 = max(0, min(int(y1 * ph), int(ph)))
                px2 = max(0, min(int(x2 * pw), int(pw)))
                py2 = max(0, min(int(y2 * ph), int(ph)))

                crop_w = px2 - px1
                crop_h = py2 - py1

                if crop_w <= 0 or crop_h <= 0:
                    results.append(CropResult(
                        raw_asset_id=ra_id, page=page_num, bbox=bbox,
                        crop_path=None, content_hash="", width=None, height=None,
                        error=f"Crop region outside page bounds: {bbox}",
                    ))
                    continue

                # Render page at target DPI
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                pix_w = int(pw * zoom)
                pix_h = int(ph * zoom)

                # Convert pixel bbox to pixmap coords
                cpx1 = max(0, min(int(px1 * zoom), pix_w))
                cpy1 = max(0, min(int(py1 * zoom), pix_h))
                cpx2 = max(0, min(int(px2 * zoom), pix_w))
                cpy2 = max(0, min(int(py2 * zoom), pix_h))

                # Crop the pixmap
                crop_rect = fitz.Rect(cpx1, cpy1, cpx2, cpy2)
                crop_pix = pix.clip(crop_rect)

                # Save as PNG
                crop_path = os.path.join(output_dir, f"{ra_id}.png")
                crop_pix.save(crop_path)

                # Hash the PNG bytes
                with open(crop_path, "rb") as f:
                    png_bytes = f.read()
                content_hash = _hash_bytes(png_bytes)

                results.append(CropResult(
                    raw_asset_id=ra_id, page=page_num, bbox=bbox,
                    crop_path=os.path.abspath(crop_path),
                    content_hash=content_hash,
                    width=crop_pix.width, height=crop_pix.height,
                    error=None,
                ))
            except Exception as exc:
                results.append(CropResult(
                    raw_asset_id=ra_id, page=page_num, bbox=bbox,
                    crop_path=None, content_hash="", width=None, height=None,
                    error=str(exc),
                ))
    finally:
        doc.close()

    return results


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]
