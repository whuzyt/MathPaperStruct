"""ADR 008: Perceptual Image Hashing v1 — Average hash (aHash) via Pillow.

Computes a 64-bit perceptual hash by resizing to 8×8 grayscale,
thresholding against the mean pixel value. The hash is stable under
moderate scaling and compression changes.

Uses Pillow (PIL) — no heavy CV models, no GPU.
"""

from __future__ import annotations

import os


def compute_phash(image_path: str, hash_size: int = 8) -> str:
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    try:
        from PIL import Image
    except ImportError:
        raise ImportError(
            "Pillow is required for perceptual hashing. "
            "Install it with: pip install Pillow"
        )

    try:
        img = Image.open(image_path)
        img = img.convert("L")  # grayscale
    except Exception as exc:
        raise ValueError(f"Cannot open image at {image_path}: {exc}")

    try:
        img = img.resize((hash_size, hash_size), Image.Resampling.LANCZOS)
    except Exception as exc:
        raise ValueError(f"Cannot resize image at {image_path}: {exc}")

    if hasattr(img, "get_flattened_data"):
        pixels = list(img.get_flattened_data())
    else:
        pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)

    bits = 0
    for i, px in enumerate(pixels):
        if px >= avg:
            bits |= 1 << (len(pixels) - 1 - i)

    return format(bits, f"0{hash_size * hash_size // 4}x")


def hamming_distance(hash_a: str, hash_b: str) -> int:
    if len(hash_a) != len(hash_b):
        raise ValueError(
            f"Hash lengths must be equal: {len(hash_a)} vs {len(hash_b)}"
        )

    try:
        int_a = int(hash_a, 16)
        int_b = int(hash_b, 16)
    except ValueError as exc:
        raise ValueError(f"Invalid hex hash: {exc}")

    return (int_a ^ int_b).bit_count()
