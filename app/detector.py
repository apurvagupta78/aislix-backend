"""YOLO detection and crop extraction."""

from __future__ import annotations

import os
import tempfile
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "best.pt"
_MODEL = None

YOLO_CONF_THRESHOLD = float(os.getenv("YOLO_CONF_THRESHOLD", "0.08"))
YOLO_CONF_SINGLE_BIN = float(os.getenv("YOLO_CONF_SINGLE_BIN", "0.24"))
YOLO_CONF_SINGLE_BIN_RETRY = float(os.getenv("YOLO_CONF_SINGLE_BIN_RETRY", "0.28"))
YOLO_CONF_SINGLE_ROW = float(os.getenv("YOLO_CONF_SINGLE_ROW", "0.16"))
YOLO_CONF_SINGLE_ROW_RETRY = float(os.getenv("YOLO_CONF_SINGLE_ROW_RETRY", "0.20"))
YOLO_CONF_MULTI_ROW = float(os.getenv("YOLO_CONF_MULTI_ROW", "0.08"))
YOLO_IOU_THRESHOLD = float(os.getenv("YOLO_IOU_THRESHOLD", "0.50"))
YOLO_DEDUP_IOU = float(os.getenv("YOLO_DEDUP_IOU", "0.55"))
YOLO_DEDUP_CONTAIN = float(os.getenv("YOLO_DEDUP_CONTAIN", "0.72"))
YOLO_IMGSZ = int(os.getenv("YOLO_IMGSZ", "1280"))
YOLO_EDGE_PAD_RATIO = float(os.getenv("YOLO_EDGE_PAD_RATIO", "0.12"))


def get_yolo_model():
    global _MODEL
    if _MODEL is None:
        if not MODEL_PATH.exists():
            raise RuntimeError(f"YOLO model not found at {MODEL_PATH}")
        from ultralytics import YOLO

        _MODEL = YOLO(str(MODEL_PATH))
    return _MODEL


def load_image_bytes(data: bytes) -> np.ndarray:
    """Decode upload bytes and apply EXIF orientation so boxes align with the captured photo."""
    from PIL import Image, ImageOps

    try:
        pil = Image.open(BytesIO(data))
        pil = ImageOps.exif_transpose(pil)
        rgb = np.array(pil.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except Exception:
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Could not decode image bytes.")
        return image


def load_image_from_url(url: str, timeout: int = 60) -> np.ndarray:
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return load_image_bytes(response.content)


def detect_products(image: np.ndarray, conf: float | None = None) -> tuple[list, int]:
    """Run YOLO; return (results, horizontal pad applied before inference)."""
    model = get_yolo_model()
    pad_x = int(image.shape[1] * YOLO_EDGE_PAD_RATIO) if YOLO_EDGE_PAD_RATIO > 0 else 0
    source = image
    if pad_x > 0:
        source = cv2.copyMakeBorder(image, 0, 0, pad_x, pad_x, cv2.BORDER_REPLICATE)
    results = model.predict(
        source=source,
        imgsz=YOLO_IMGSZ,
        conf=conf if conf is not None else YOLO_CONF_THRESHOLD,
        iou=YOLO_IOU_THRESHOLD,
        save=False,
        verbose=False,
    )
    return results, pad_x


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


def _containment_ratio(inner: np.ndarray, outer: np.ndarray) -> float:
    ix1 = max(float(inner[0]), float(outer[0]))
    iy1 = max(float(inner[1]), float(outer[1]))
    ix2 = min(float(inner[2]), float(outer[2]))
    iy2 = min(float(inner[3]), float(outer[3]))
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    inner_area = _box_area(inner)
    return inter / inner_area if inner_area > 0 else 0.0


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

    # Drop cap/tag fragments nested inside a larger box on the same row.
    kept.sort(key=lambda idx: _box_area(boxes[idx]), reverse=True)
    final: list[int] = []
    for idx in kept:
        box = boxes[idx]
        box_area = _box_area(box)
        nested = False
        for kept_idx in final:
            outer_area = _box_area(boxes[kept_idx])
            if outer_area <= box_area:
                continue
            if not _same_shelf_row(box, boxes[kept_idx]):
                continue
            if box_area / outer_area <= 0.45 and _containment_ratio(box, boxes[kept_idx]) >= YOLO_DEDUP_CONTAIN:
                nested = True
                break
        if not nested:
            final.append(idx)
    final.sort()
    return [boxes[idx] for idx in final]


def get_boxes(results, *, pad_x: int = 0, max_x: int | None = None) -> list[np.ndarray]:
    boxes: list[np.ndarray] = []
    confidences: list[float] = []
    for result in results:
        if result.boxes is None:
            continue
        xyxy = result.boxes.xyxy.cpu().numpy()
        conf = result.boxes.conf.cpu().numpy()
        for index, box in enumerate(xyxy):
            adjusted = box.copy()
            if pad_x:
                adjusted[0] -= pad_x
                adjusted[2] -= pad_x
            if max_x is not None:
                adjusted[0] = max(0.0, adjusted[0])
                adjusted[2] = min(float(max_x), adjusted[2])
            boxes.append(adjusted)
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
