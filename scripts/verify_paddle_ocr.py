"""Verify PaddleOCR imports and pre-downloads English models (Docker build step)."""

from __future__ import annotations

import sys


def main() -> None:
    try:
        from paddleocr import PaddleOCR

        PaddleOCR(
            use_angle_cls=True,
            lang="en",
            use_gpu=False,
            show_log=False,
            det_db_thresh=0.25,
            rec_batch_num=8,
        )
    except Exception as exc:
        print(f"PaddleOCR verification failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("PaddleOCR verification OK")


if __name__ == "__main__":
    main()
