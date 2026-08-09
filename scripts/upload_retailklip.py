#!/usr/bin/env python3
"""Upload RetailKLIP checkpoint to Supabase storage for Railway deploy."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.catalog_sync import upload_retailklip_checkpoint  # noqa: E402
from app.retailklip import DEFAULT_CHECKPOINT, DEFAULT_META  # noqa: E402


def main() -> None:
    if not DEFAULT_CHECKPOINT.exists():
        raise SystemExit(f"Checkpoint not found: {DEFAULT_CHECKPOINT}")
    upload_retailklip_checkpoint(DEFAULT_CHECKPOINT, DEFAULT_META)
    print("Done.")


if __name__ == "__main__":
    main()
