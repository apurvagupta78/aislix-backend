"""YOLO detection and crop extraction."""

from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np
import requests
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "best.pt"
MODEL = YOLO(str(MODEL_PATH)) if MODEL_PATH.exists() else None


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
    if MODEL is None:
        raise RuntimeError(f"YOLO model not found at {MODEL_PATH}")
    return MODEL.predict(source=image, imgsz=640, conf=0.05, save=False, verbose=False)


def get_boxes(results) -> list[np.ndarray]:
    boxes = []
    for result in results:
        if result.boxes is not None:
            boxes.extend(result.boxes.xyxy.cpu().numpy())
    return boxes


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
