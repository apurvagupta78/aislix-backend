#!/usr/bin/env python3
"""Fail Docker/Railway build if RetailKLIP checkpoint is missing or a Git LFS stub."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECKPOINT = ROOT / "models" / "retailklip_vitb32.pt"
META = ROOT / "models" / "retailklip_vitb32.json"
MIN_BYTES = 1_000_000


def main() -> None:
    if not CHECKPOINT.exists():
        raise SystemExit(f"ERROR: RetailKLIP checkpoint not found: {CHECKPOINT}")
    size = CHECKPOINT.stat().st_size
    if size < MIN_BYTES:
        raise SystemExit(
            f"ERROR: {CHECKPOINT.name} is only {size} bytes — Git LFS pointer, not the model.\n"
            "Run: git lfs pull\n"
            "Railway: ensure Git LFS is enabled and Dockerfile runs git lfs pull before this check."
        )
    if not META.exists():
        raise SystemExit(f"ERROR: RetailKLIP metadata not found: {META}")
    print(f"RetailKLIP checkpoint OK: {size / 1_000_000:.1f} MB")


if __name__ == "__main__":
    main()
