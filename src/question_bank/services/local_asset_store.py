"""ADR 007: Local Asset Store v1 — Store cropped assets to local filesystem.

Deterministic paths under {root_dir}/assets/{paper_id}/{raw_asset_id}.png.
Atomic writes via temp file + rename. Idempotent: same content_hash skips re-write.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass

from question_bank.services.pdf_cropper import CropResult


@dataclass(slots=True)
class StoredAsset:
    raw_asset_id: str
    storage_url: str
    file_path: str
    content_hash: str
    width: int | None
    height: int | None


def store_crop_result(
    crop_result: CropResult,
    root_dir: str,
    paper_id: str,
) -> StoredAsset:
    if crop_result.error is not None:
        raise ValueError(
            f"Cannot store failed crop for {crop_result.raw_asset_id}: "
            f"{crop_result.error}"
        )

    if crop_result.crop_path is None:
        raise ValueError(
            f"Cannot store crop for {crop_result.raw_asset_id}: crop_path is None"
        )

    target_dir = os.path.join(root_dir, "assets", paper_id)
    os.makedirs(target_dir, exist_ok=True)

    target_path = os.path.join(target_dir, f"{crop_result.raw_asset_id}.png")

    # Idempotent: if target already exists with same content_hash, skip
    if os.path.exists(target_path):
        with open(target_path, "rb") as f:
            existing_hash = _hash_file_bytes(f.read())
        if existing_hash == crop_result.content_hash:
            return StoredAsset(
                raw_asset_id=crop_result.raw_asset_id,
                storage_url=_build_storage_url(paper_id, crop_result.raw_asset_id),
                file_path=os.path.abspath(target_path),
                content_hash=crop_result.content_hash,
                width=crop_result.width,
                height=crop_result.height,
            )

    # Atomic write: write to temp file, then rename
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".png", prefix=f"{crop_result.raw_asset_id}_", dir=target_dir
    )
    try:
        os.close(tmp_fd)
        shutil.copy2(crop_result.crop_path, tmp_path)
        os.rename(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return StoredAsset(
        raw_asset_id=crop_result.raw_asset_id,
        storage_url=_build_storage_url(paper_id, crop_result.raw_asset_id),
        file_path=os.path.abspath(target_path),
        content_hash=crop_result.content_hash,
        width=crop_result.width,
        height=crop_result.height,
    )


def _build_storage_url(paper_id: str, raw_asset_id: str) -> str:
    return f"local://assets/{paper_id}/{raw_asset_id}.png"


def _hash_file_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]
