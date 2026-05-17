from __future__ import annotations

import hashlib
import os
import tempfile
import unittest

from question_bank.services.local_asset_store import (
    StoredAsset,
    store_crop_result,
)
from question_bank.services.pdf_cropper import CropResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_crop_result(
    ra_id: str = "ra_abc123",
    page: int = 1,
    bbox: tuple[float, float, float, float] = (0.1, 0.2, 0.5, 0.6),
    content_hash: str = "deadbeef12345678",
    width: int = 200,
    height: int = 150,
    tmp_dir: str | None = None,
) -> CropResult:
    if tmp_dir is None:
        tmp_dir = tempfile.mkdtemp()

    # Write a small PNG file as the crop
    crop_path = os.path.join(tmp_dir, f"{ra_id}.png")
    png_bytes = b"\x89PNG\r\n\x1a\n" + os.urandom(64)
    with open(crop_path, "wb") as f:
        f.write(png_bytes)

    actual_hash = hashlib.sha256(png_bytes).hexdigest()[:16]

    return CropResult(
        raw_asset_id=ra_id,
        page=page,
        bbox=bbox,
        crop_path=crop_path,
        content_hash=actual_hash,
        width=width,
        height=height,
        error=None,
    )


# ---------------------------------------------------------------------------
# TestPathDeterministic
# ---------------------------------------------------------------------------


class TestPathDeterministic(unittest.TestCase):
    def test_same_inputs_same_path(self):
        cr = _make_crop_result()
        root = tempfile.mkdtemp()

        sa1 = store_crop_result(cr, root, "paper_01")
        sa2 = store_crop_result(cr, root, "paper_01")

        self.assertEqual(sa1.file_path, sa2.file_path)

    def test_path_follows_assets_paper_id_raw_asset_id_pattern(self):
        cr = _make_crop_result(ra_id="ra_xyz")
        root = tempfile.mkdtemp()

        sa = store_crop_result(cr, root, "paper_42")

        expected_suffix = os.path.join("assets", "paper_42", "ra_xyz.png")
        self.assertTrue(sa.file_path.endswith(expected_suffix),
                        f"Expected path to end with {expected_suffix}, got {sa.file_path}")

    def test_creates_parent_directories(self):
        cr = _make_crop_result()
        root = tempfile.mkdtemp()
        # Remove the root so we verify mkdir happens
        import shutil
        shutil.rmtree(root)

        sa = store_crop_result(cr, root, "paper_01")
        self.assertTrue(os.path.isdir(os.path.dirname(sa.file_path)))
        self.assertTrue(os.path.isfile(sa.file_path))


# ---------------------------------------------------------------------------
# TestAtomicWrite
# ---------------------------------------------------------------------------


class TestAtomicWrite(unittest.TestCase):
    def test_temp_file_renamed_not_left_on_disk(self):
        cr = _make_crop_result()
        root = tempfile.mkdtemp()

        target_dir = os.path.join(root, "assets", "paper_01")
        os.makedirs(target_dir, exist_ok=True)

        # Store should not leave .tmp files
        sa = store_crop_result(cr, root, "paper_01")

        tmp_files = [f for f in os.listdir(target_dir) if f.endswith(".tmp")]
        self.assertEqual(len(tmp_files), 0,
                         f"Temp files left behind: {tmp_files}")

        # The actual file should exist
        self.assertTrue(os.path.isfile(sa.file_path))


# ---------------------------------------------------------------------------
# TestIdempotentStore
# ---------------------------------------------------------------------------


class TestIdempotentStore(unittest.TestCase):
    def test_same_content_hash_writes_only_once(self):
        cr = _make_crop_result()
        root = tempfile.mkdtemp()

        sa1 = store_crop_result(cr, root, "paper_01")
        mtime1 = os.path.getmtime(sa1.file_path)
        with open(sa1.file_path, "rb") as f:
            content1 = f.read()

        # Store again — should skip write, file unchanged
        sa2 = store_crop_result(cr, root, "paper_01")
        mtime2 = os.path.getmtime(sa2.file_path)
        with open(sa2.file_path, "rb") as f:
            content2 = f.read()

        self.assertEqual(content1, content2)
        self.assertAlmostEqual(mtime1, mtime2, places=1)

    def test_different_content_hash_overwrites(self):
        cr1 = _make_crop_result(content_hash="aaa111")
        root = tempfile.mkdtemp()

        target_dir = os.path.join(root, "assets", "paper_01")
        os.makedirs(target_dir, exist_ok=True)
        target_path = os.path.join(target_dir, f"{cr1.raw_asset_id}.png")

        # Write a file directly with different content
        with open(target_path, "wb") as f:
            f.write(b"different content")

        # Now store — should overwrite because content_hash differs
        sa = store_crop_result(cr1, root, "paper_01")
        with open(sa.file_path, "rb") as f:
            actual = f.read()

        # Should now contain cr1's content (not "different content")
        with open(cr1.crop_path, "rb") as f:
            expected = f.read()
        self.assertEqual(actual, expected)


# ---------------------------------------------------------------------------
# TestStorageUrl
# ---------------------------------------------------------------------------


class TestStorageUrl(unittest.TestCase):
    def test_returns_local_url(self):
        cr = _make_crop_result(ra_id="ra_hello")
        root = tempfile.mkdtemp()

        sa = store_crop_result(cr, root, "paper_99")

        self.assertEqual(
            sa.storage_url,
            "local://assets/paper_99/ra_hello.png",
        )


# ---------------------------------------------------------------------------
# TestRejectsFailedCrop
# ---------------------------------------------------------------------------


class TestRejectsFailedCrop(unittest.TestCase):
    def test_raises_on_failed_crop_result(self):
        cr = CropResult(
            raw_asset_id="ra_bad", page=1, bbox=(0.0, 0.0, 0.0, 0.0),
            crop_path=None, content_hash="", width=None, height=None,
            error="Something went wrong",
        )
        root = tempfile.mkdtemp()

        with self.assertRaises(ValueError) as ctx:
            store_crop_result(cr, root, "paper_01")
        self.assertIn("Cannot store failed crop", str(ctx.exception))
        self.assertIn("ra_bad", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
