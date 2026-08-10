"""Verify PaddleOCR imports and pre-downloads English models (Docker build step)."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    # Bake models into /app so runtime matches build (Railway uses same HOME).
    app_home = Path(os.environ.get("APP_HOME", "/app"))
    app_home.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(app_home)

    try:
        os.environ["FLAGS_use_mkldnn"] = "0"
        from paddleocr import PaddleOCR

        base_kwargs = {
            "use_angle_cls": True,
            "lang": "en",
            "use_gpu": False,
            "show_log": False,
            "det_db_thresh": 0.25,
            "rec_batch_num": 8,
        }
        try:
            PaddleOCR(**base_kwargs, enable_mkldnn=False)
        except TypeError:
            PaddleOCR(**base_kwargs)
    except Exception as exc:
        print(f"PaddleOCR verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"PaddleOCR verification OK (home={app_home})")


if __name__ == "__main__":
    main()
