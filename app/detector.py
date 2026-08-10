"""YOLO detection and crop extraction."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import cv2
import numpy as np
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "best.pt"
_MODEL = None

YOLO_CONF_THRESHOLD = float(os.getenv("YOLO_CONF_THRESHOLD", "0.25"))
YOLO_IOU_THRESHOLD = float(os.getenv("YOLO_IOU_THRESHOLD", "0.50"))
YOLO_DEDUP_IOU = float(os.getenv("YOLO_DEDUP_IOU", "0.55"))
YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", "640"))


def get_yolo_model():
    global _MODEL
    if _MODEL is None:
        if not MODEL_PATH.exists():
            raise RuntimeError(f"YOLO model not found at {MODEL_PATH}")
        from ultralytics import YOLO

        _MODEL = YOLO(str(MODEL_PATH))
    return _MODEL


def load_image_bytes(data: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode image bytes.")
    return image


def load_image_from_url(url: str, timeout: int = 60) -> np.ndarray:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return load_image_bytes(response.content)


def detect_products(image: np.ndarray):
    model = get_yolo_model()
    return model.predict(
        source=image,
        imgsz=YOLO_IMGSZ,
        conf=YOLO_CONF_THRESHOLD,
        iou=YOLO_IOU_THRESHOLD,
        save=False,
        verbose=False,
    )


def _box_area(box: np.ndarray) -> float:
    x1, y1, x2, y2 = box
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def _box_iou(a: np.ndarray, b: np.ndarray) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    union = _box_area(a) + _box_area(b) - inter
    return inter / union if union > 0 else 0.0


def _same_shelf_row(a: np.ndarray, b: np.ndarray) -> bool:
    ay1, ay2 = float(a[1]), float(a[3])
    by1, by2 = float(b[1]), float(b[3])
    if ay2 <= ay1 or by2 <= by1:
        return True
    acy = (ay1 + ay2) / 2.0
    bcy = (by1 + by2) / 2.0
    row_tol = max(ay2 - ay1, by2 - by1) * 0.55
    return abs(acy - bcy) <= row_tol


def deduplicate_boxes(
    boxes: list[np.ndarray],
    confidences: list[float] | None = None,
    iou_threshold: float | None = None,
) -> list[np.ndarray]:
    """Merge overlapping detections on the same shelf row (keep largest / highest conf)."""
    if len(boxes) <= 1:
        return boxes

    iou_threshold = iou_threshold if iou_threshold is not None else YOLO_DEDUP_IOU
    confidences = confidences or [1.0] * len(boxes)
    order = sorted(
        range(len(boxes)),
        key=lambda idx: (confidences[idx], _box_area(boxes[idx])),
        reverse=True,
    )
    kept: list[int] = []
    for idx in order:
        box = boxes[idx]
        duplicate = False
        for kept_idx in kept:
            if not _same_shelf_row(box, boxes[kept_idx]):
                continue
            if _box_iou(box, boxes[kept_idx]) >= iou_threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(idx)
    kept.sort()
    return [boxes[idx] for idx in kept]


def get_boxes(results) -> list[np.ndarray]:
    boxes: list[np.ndarray] = []
    confidences: list[float] = []
    for result in results:
        if result.boxes is None:
            continue
        xyxy = result.boxes.xyxy.cpu().numpy()
        conf = result.boxes.conf.cpu().numpy()
        for index, box in enumerate(xyxy):
            boxes.append(box)
            confidences.append(float(conf[index]) if index < len(conf) else 0.0)
    return deduplicate_boxes(boxes, confidences)


def crop_products(image: np.ndarray, boxes, work_dir: Path | None = None) -> tuple[list[dict], Path]:
    work_dir = work_dir or Path(tempfile.mkdtemp(prefix="aislix_crops_"))
    work_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for index, box in enumerate(boxes):
        x1, y1, x2, y2 = map(int, box)
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        filename = work_dir / f"product_{index:04d}.jpg"
        cv2.imwrite(str(filename), crop)
        records.append(
            {
                "image_path": str(filename),
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
            }
        )
    return records, work_dir
