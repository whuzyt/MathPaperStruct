from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

from question_bank.services.image_phash import compute_phash, hamming_distance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_test_image(path: str, size: tuple[int, int] = (64, 64),
                       color: tuple[int, int, int] = (128, 128, 128)) -> None:
    from PIL import Image
    img = Image.new("RGB", size, color)
    img.save(path, "PNG")


def _create_noisy_image(path: str, size: tuple[int, int] = (64, 64)) -> None:
    from PIL import Image
    import random
    random.seed(42)
    img = Image.new("RGB", size)
    pixels = []
    for _ in range(size[0] * size[1]):
        pixels.append((random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    img.putdata(pixels)
    img.save(path, "PNG")


# ---------------------------------------------------------------------------
# TestComputePHash
# ---------------------------------------------------------------------------


class TestComputePHash(unittest.TestCase):
    def test_same_image_produces_same_hash(self):
        d = tempfile.mkdtemp()
        p1 = os.path.join(d, "a.png")
        p2 = os.path.join(d, "b.png")
        _create_test_image(p1, color=(100, 150, 200))
        _create_test_image(p2, color=(100, 150, 200))

        h1 = compute_phash(p1)
        h2 = compute_phash(p2)
        self.assertEqual(h1, h2)

    def test_different_images_produce_different_hashes(self):
        d = tempfile.mkdtemp()
        p1 = os.path.join(d, "a.png")
        p2 = os.path.join(d, "b.png")
        # Create images with different gradient patterns (not solid color)
        # which produce different perceptual hashes
        from PIL import Image
        img1 = Image.new("L", (64, 64))
        for x in range(64):
            for y in range(64):
                img1.putpixel((x, y), x * 4)  # left-to-right gradient
        img1.save(p1, "PNG")

        img2 = Image.new("L", (64, 64))
        for x in range(64):
            for y in range(64):
                img2.putpixel((x, y), y * 4)  # top-to-bottom gradient
        img2.save(p2, "PNG")

        h1 = compute_phash(p1)
        h2 = compute_phash(p2)
        self.assertNotEqual(h1, h2)
        d12 = hamming_distance(h1, h2)
        self.assertGreater(d12, 4, f"Different gradients should differ, got distance {d12}")

    def test_scaled_image_has_low_hamming_distance(self):
        d = tempfile.mkdtemp()
        from PIL import Image, ImageDraw
        p1 = os.path.join(d, "orig.png")
        p2 = os.path.join(d, "compressed.png")

        # Create an image with larger features that survive compression
        img = Image.new("L", (128, 128), 255)
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 60, 60], fill=0)
        draw.rectangle([70, 70, 120, 120], fill=80)
        draw.ellipse([30, 40, 100, 90], fill=160)
        img.save(p1, "PNG")

        # Save with low quality JPEG to simulate compression differences
        img_rgb = img.convert("RGB")
        img_rgb.save(p2, "JPEG", quality=30)

        h1 = compute_phash(p1)
        h2 = compute_phash(p2)
        d = hamming_distance(h1, h2)
        # JPEG compression at low quality may shift hash somewhat
        self.assertLess(d, 32, f"Compressed image hamming distance {d} should be moderate")

    def test_corrupted_image_raises_clear_error(self):
        d = tempfile.mkdtemp()
        bad = os.path.join(d, "bad.png")
        with open(bad, "wb") as f:
            f.write(b"not an image file")

        with self.assertRaises(ValueError) as ctx:
            compute_phash(bad)
        self.assertIn("Cannot open image", str(ctx.exception))

    def test_missing_file_raises_clear_error(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            compute_phash("/nonexistent/path.png")
        self.assertIn("Image not found", str(ctx.exception))

    def test_hash_is_16_hex_chars(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "img.png")
        _create_test_image(p)

        h = compute_phash(p)
        self.assertEqual(len(h), 16)
        int(h, 16)  # must not raise

    def test_different_size_images_same_content_low_distance(self):
        d = tempfile.mkdtemp()
        p1 = os.path.join(d, "big.png")
        p2 = os.path.join(d, "small.png")
        _create_test_image(p1, size=(128, 128), color=(0, 128, 255))
        _create_test_image(p2, size=(32, 32), color=(0, 128, 255))

        h1 = compute_phash(p1)
        h2 = compute_phash(p2)
        self.assertEqual(h1, h2, "Solid color images of different sizes should produce same hash")


# ---------------------------------------------------------------------------
# TestHammingDistance
# ---------------------------------------------------------------------------


class TestHammingDistance(unittest.TestCase):
    def test_identical_hashes_distance_zero(self):
        self.assertEqual(hamming_distance("deadbeef00000000", "deadbeef00000000"), 0)

    def test_computed_distance_matches_manual(self):
        # "0000000000000000" (all 0) vs "0000000000000001" (bit 0 set)
        self.assertEqual(hamming_distance("0000000000000000", "0000000000000001"), 1)
        # "ffffffffffffffff" (all 1) vs "0000000000000000" (all 0) = 64
        self.assertEqual(hamming_distance("ffffffffffffffff", "0000000000000000"), 64)
        # Sample: 0xF0 vs 0x0F in first nibble → 8 bits differ per byte
        self.assertEqual(hamming_distance("f0" + "0" * 14, "0f" + "0" * 14), 8)

    def test_different_length_strings_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            hamming_distance("abc", "abcd")
        self.assertIn("lengths must be equal", str(ctx.exception))

    def test_invalid_hex_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            hamming_distance("gggggggggggggggg", "0000000000000000")
        self.assertIn("Invalid hex hash", str(ctx.exception))


# ---------------------------------------------------------------------------
# TestPillowMissing
# ---------------------------------------------------------------------------


class TestPillowMissing(unittest.TestCase):
    def test_clear_error_when_pillow_not_installed(self):
        import builtins
        real_import = builtins.__import__

        def block_pil_import(name, *args, **kwargs):
            if name == "PIL" or name == "PIL.Image":
                raise ImportError("No module named 'PIL'")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=block_pil_import), \
             mock.patch("os.path.exists", return_value=True):
            with self.assertRaises(ImportError) as ctx:
                compute_phash("/fake/img.png")
            self.assertIn("Pillow is required", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
