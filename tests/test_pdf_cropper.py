from __future__ import annotations

import builtins
import os
import sys
import unittest
from unittest import mock

from question_bank.services.pdf_cropper import CropResult, crop_pdf_assets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_raw_asset_dict(
    ra_id: str = "ra_abc123",
    page: int = 1,
    bbox: tuple[float, float, float, float] = (0.1, 0.2, 0.5, 0.6),
    asset_type: str = "image",
) -> dict:
    import json as _json

    return {
        "id": ra_id,
        "paper_id": "paper_01",
        "page": page,
        "bbox_json": _json.dumps(bbox),
        "asset_type": asset_type,
    }


def _make_mock_page(page_width=612, page_height=792):
    """Create a mock fitz page with given pixel dimensions."""
    p = mock.MagicMock()
    p.rect.width = page_width
    p.rect.height = page_height

    png_data = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\n\x00\x00\x00\n"
        b"\x08\x02\x00\x00\x00\x02PK\xb2\x00\x00\x00\x01sRGB\x00\xae\xce"
        b"\x1c\xe9\x00\x00\x00\x04gAMA\x00\x00\xb1\x8f\x0b\xfca\x05\x00"
        b"\x00\x00\x0cPLTE\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00"
        b"\x00\xe6\xe6f\x00\x00\x00\x05tRNS\x00\x00\x00\x00@\xa8\x97"
        b"\x19\x00\x00\x00\x0eIDAT\x08\xd7c\x60`\x00\x00\x00\x02\x00"
        b"\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    crop_pix = mock.MagicMock()
    crop_pix.width = 80
    crop_pix.height = 80
    def _save_png(path):
        with open(path, "wb") as f:
            f.write(png_data)
    crop_pix.save = _save_png

    p.get_pixmap.return_value = crop_pix
    return p, png_data


def _make_mock_doc(pages):
    doc = mock.MagicMock()
    doc.__len__ = lambda self: len(pages)
    doc.__getitem__ = lambda self, i: pages[i]
    return doc


# Patch set for tests that mock fitz internals (avoids FileNotFoundError
# on fake PDF paths by also mocking os.path.exists).
def _fitz_mocks(doc):
    return (
        mock.patch("os.path.exists", return_value=True),
        mock.patch("fitz.open", return_value=doc),
        mock.patch("fitz.Matrix", lambda x, y: mock.MagicMock()),
        mock.patch("fitz.Rect", lambda x1, y1, x2, y2: (x1, y1, x2, y2)),
    )


# ---------------------------------------------------------------------------
# TestBboxConversion
# ---------------------------------------------------------------------------


class TestBboxConversion(unittest.TestCase):
    def test_normalized_to_pixel_correct(self):
        page, _png = _make_mock_page(612, 792)
        doc = _make_mock_doc([page])
        ra = _make_raw_asset_dict(bbox=(0.1, 0.2, 0.5, 0.6))
        out = _tmp_dir()

        mocks = _fitz_mocks(doc)
        with mocks[0], mocks[1], mocks[2], mocks[3]:
            results = crop_pdf_assets("/fake/pdf.pdf", [ra], out)

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].error, f"Unexpected error: {results[0].error}")
        self.assertIsNotNone(results[0].crop_path)
        self.assertGreater(results[0].width, 0)
        self.assertGreater(results[0].height, 0)

    def test_different_page_sizes_produce_different_pixel_bbox(self):
        page_small, _ = _make_mock_page(400, 500)
        page_large, _ = _make_mock_page(800, 1000)
        ra = _make_raw_asset_dict(bbox=(0.1, 0.1, 0.9, 0.9))
        out_small = _tmp_dir()
        out_large = _tmp_dir()

        for mocks in _fitz_mocks(_make_mock_doc([page_small])):
            mocks.start()
        try:
            r_small = crop_pdf_assets("/fake/small.pdf", [ra], out_small)
        finally:
            for m in _fitz_mocks(_make_mock_doc([page_small])):
                m.stop()

        for mocks in _fitz_mocks(_make_mock_doc([page_large])):
            mocks.start()
        try:
            r_large = crop_pdf_assets("/fake/large.pdf", [ra], out_large)
        finally:
            for m in _fitz_mocks(_make_mock_doc([page_large])):
                m.stop()

        self.assertEqual(len(r_small), 1)
        self.assertEqual(len(r_large), 1)


# ---------------------------------------------------------------------------
# TestBboxClamp
# ---------------------------------------------------------------------------


class TestBboxClamp(unittest.TestCase):
    def test_bbox_beyond_page_clamped(self):
        page, _ = _make_mock_page(612, 792)
        doc = _make_mock_doc([page])
        ra = _make_raw_asset_dict(bbox=(-0.5, -0.5, 1.5, 1.5))
        out = _tmp_dir()

        mocks = _fitz_mocks(doc)
        with mocks[0], mocks[1], mocks[2], mocks[3]:
            results = crop_pdf_assets("/fake/c.pdf", [ra], out)

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].error)

    def test_negative_coords_clamped_to_zero(self):
        page, _ = _make_mock_page(612, 792)
        doc = _make_mock_doc([page])
        ra = _make_raw_asset_dict(bbox=(-0.1, -0.1, 0.3, 0.3))
        out = _tmp_dir()

        mocks = _fitz_mocks(doc)
        with mocks[0], mocks[1], mocks[2], mocks[3]:
            results = crop_pdf_assets("/fake/d.pdf", [ra], out)

        self.assertEqual(len(results), 1)
        self.assertIsNone(results[0].error)


# ---------------------------------------------------------------------------
# TestInvalidBbox
# ---------------------------------------------------------------------------


class TestInvalidBbox(unittest.TestCase):
    def test_zero_area_bbox_returns_error(self):
        page, _ = _make_mock_page(612, 792)
        doc = _make_mock_doc([page])
        ra = _make_raw_asset_dict(bbox=(0.2, 0.3, 0.2, 0.5))  # x1==x2
        out = _tmp_dir()

        mocks = _fitz_mocks(doc)
        with mocks[0], mocks[1], mocks[2], mocks[3]:
            results = crop_pdf_assets("/fake/e.pdf", [ra], out)

        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].error)
        self.assertIn("Invalid bbox", results[0].error)
        self.assertIsNone(results[0].crop_path)
        self.assertEqual(results[0].content_hash, "")

    def test_negative_area_bbox_returns_error(self):
        page, _ = _make_mock_page(612, 792)
        doc = _make_mock_doc([page])
        ra = _make_raw_asset_dict(bbox=(0.5, 0.5, 0.1, 0.1))  # x2<x1, y2<y1
        out = _tmp_dir()

        mocks = _fitz_mocks(doc)
        with mocks[0], mocks[1], mocks[2], mocks[3]:
            results = crop_pdf_assets("/fake/f.pdf", [ra], out)

        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0].error)
        self.assertIn("Invalid bbox", results[0].error)

    def test_error_does_not_abort_batch(self):
        page, _ = _make_mock_page(612, 792)
        doc = _make_mock_doc([page])
        bad = _make_raw_asset_dict(ra_id="ra_bad", bbox=(0.5, 0.5, 0.1, 0.1))
        good = _make_raw_asset_dict(ra_id="ra_good", bbox=(0.1, 0.1, 0.9, 0.9))
        out = _tmp_dir()

        mocks = _fitz_mocks(doc)
        with mocks[0], mocks[1], mocks[2], mocks[3]:
            results = crop_pdf_assets("/fake/g.pdf", [bad, good], out)

        self.assertEqual(len(results), 2)
        self.assertIsNotNone(results[0].error)
        self.assertIsNone(results[1].error)
        self.assertIsNotNone(results[1].crop_path)


# ---------------------------------------------------------------------------
# TestContentHash
# ---------------------------------------------------------------------------


class TestContentHash(unittest.TestCase):
    def test_content_hash_is_sha256_of_png_bytes(self):
        import hashlib

        page, png_data = _make_mock_page(612, 792)
        doc = _make_mock_doc([page])
        ra = _make_raw_asset_dict(bbox=(0.1, 0.1, 0.9, 0.9))
        out = _tmp_dir()

        mocks = _fitz_mocks(doc)
        with mocks[0], mocks[1], mocks[2], mocks[3]:
            results = crop_pdf_assets("/fake/h.pdf", [ra], out)

        expected_hash = hashlib.sha256(png_data).hexdigest()[:16]
        self.assertEqual(results[0].content_hash, expected_hash)

    def test_different_images_different_hashes(self):
        import hashlib

        png_data_1 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\n\x00\x00\x00\n"
            b"\x08\x02\x00\x00\x00\x02PK\xb2\x00\x00\x00\x01sRGB\x00\xae\xce"
            b"\x1c\xe9\x00\x00\x00\x04gAMA\x00\x00\xb1\x8f\x0b\xfca\x05\x00"
            b"\x00\x00\x0cPLTE\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\xe6\xe6f\x00\x00\x00\x05tRNS\x00\x00\x00\x00@\xa8\x97"
            b"\x19\x00\x00\x00\x0eIDAT\x08\xd7c\x60`\x00\x00\x00\x02\x00"
            b"\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        png_data_2 = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x0b\x00\x00\x00\x0b"
            b"\x08\x02\x00\x00\x00\x03\x01\x13\xa2\x00\x00\x00\x01sRGB\x00\xae\xce"
            b"\x1c\xe9\x00\x00\x00\x04gAMA\x00\x00\xb1\x8f\x0b\xfca\x05\x00"
            b"\x00\x00\x0cPLTE\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\xe6\xe6f\x00\x00\x00\x05tRNS\x00\x00\x00\x00@\xa8\x97"
            b"\x19\x00\x00\x00\x0eIDAT\x08\xd7c\x60`\x00\x00\x00\x02\x00"
            b"\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        self.assertNotEqual(
            hashlib.sha256(png_data_1).hexdigest()[:16],
            hashlib.sha256(png_data_2).hexdigest()[:16],
        )


# ---------------------------------------------------------------------------
# TestPyMuPDFMissing
# ---------------------------------------------------------------------------


class TestPyMuPDFMissing(unittest.TestCase):
    def test_clear_error_when_fitz_not_installed(self):
        real_import = builtins.__import__

        def block_fitz_import(name, *args, **kwargs):
            if name == "fitz":
                raise ImportError("No module named 'fitz'")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=block_fitz_import), \
             mock.patch("os.path.exists", return_value=True):
            with self.assertRaises(ImportError) as ctx:
                crop_pdf_assets("/fake/i.pdf", [], "/tmp/out")
            self.assertIn("PyMuPDF", str(ctx.exception))
            self.assertIn("fitz", str(ctx.exception))


# ---------------------------------------------------------------------------
# TestCropResultFields
# ---------------------------------------------------------------------------


class TestCropResultFields(unittest.TestCase):
    def test_successful_crop_has_all_fields(self):
        page, _ = _make_mock_page(612, 792)
        doc = _make_mock_doc([page])
        ra = _make_raw_asset_dict(bbox=(0.1, 0.1, 0.9, 0.9))
        out = _tmp_dir()

        mocks = _fitz_mocks(doc)
        with mocks[0], mocks[1], mocks[2], mocks[3]:
            results = crop_pdf_assets("/fake/j.pdf", [ra], out)

        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.raw_asset_id, "ra_abc123")
        self.assertEqual(r.page, 1)
        self.assertEqual(r.bbox, (0.1, 0.1, 0.9, 0.9))
        self.assertIsNotNone(r.crop_path)
        self.assertTrue(os.path.isfile(r.crop_path))
        self.assertNotEqual(r.content_hash, "")
        self.assertGreater(r.width, 0)
        self.assertGreater(r.height, 0)
        self.assertIsNone(r.error)


def _tmp_dir():
    import tempfile
    return tempfile.mkdtemp()


if __name__ == "__main__":
    unittest.main()
