"""Measurements of an audit evidence photo for the server-side photo rules.

The frontend repeats the checks it runs on the auditee's phone (capture time, blur, darkness,
glare, duplicates) against these numbers, so a modified client cannot skip them.
Brightness and sharpness use the same method as the phone check: the photo scaled so its longest
edge is 320 px, ITU-R 601 luma, and the variance of a 4-neighbour Laplacian.
"""

from __future__ import annotations

import hashlib
import io

import numpy as np
import requests
from PIL import Image, ImageOps

MAX_PHOTO_BYTES = 15 * 1024 * 1024
ANALYSIS_EDGE = 320

_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 0x9003
_OFFSET_TIME_ORIGINAL = 0x9011
_DATETIME = 0x0132


def download_photo(url: str, timeout: int = 20) -> bytes:
    with requests.get(url, stream=True, timeout=timeout) as response:
        if response.status_code != 200:
            raise ValueError("Could not open the photo from storage.")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_PHOTO_BYTES:
                raise ValueError("Photo is larger than 15 MB.")
            chunks.append(chunk)
    return b"".join(chunks)


def _exif_capture(image: Image.Image) -> tuple[str | None, str | None]:
    """Camera capture time ("YYYY:MM:DD HH:MM:SS", local) and its UTC offset ("+05:30") when present."""
    try:
        exif = image.getexif()
    except Exception:
        return None, None
    if not exif:
        return None, None
    try:
        sub = exif.get_ifd(_EXIF_IFD)
    except Exception:
        sub = {}
    taken = sub.get(_DATETIME_ORIGINAL) or exif.get(_DATETIME)
    offset = sub.get(_OFFSET_TIME_ORIGINAL)
    taken = str(taken).strip("\x00 ") if taken else None
    offset = str(offset).strip("\x00 ") if offset else None
    return taken or None, offset or None


def _luma(image: Image.Image) -> np.ndarray:
    return np.asarray(image.convert("RGB").convert("L"), dtype=np.float64)


def laplacian_variance(gray: np.ndarray) -> float:
    if gray.shape[0] < 3 or gray.shape[1] < 3:
        return 0.0
    center = gray[1:-1, 1:-1]
    lap = 4 * center - gray[:-2, 1:-1] - gray[2:, 1:-1] - gray[1:-1, :-2] - gray[1:-1, 2:]
    return float(lap.var())


def difference_hash(image: Image.Image) -> str:
    """64-bit difference hash as 16 hex characters (row-major, left pixel brighter = 1)."""
    small = _luma(image.resize((9, 8), Image.BILINEAR))
    bits = (small[:, :-1] > small[:, 1:]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def photo_metrics(data: bytes) -> dict:
    metrics: dict = {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "decodable": False,
        "width": None,
        "height": None,
        "exif_taken_at": None,
        "exif_offset": None,
        "brightness": None,
        "sharpness": None,
        "dhash": None,
    }
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        return metrics
    metrics["exif_taken_at"], metrics["exif_offset"] = _exif_capture(image)
    image = ImageOps.exif_transpose(image)
    width, height = image.size
    scale = min(1.0, ANALYSIS_EDGE / max(width, height))
    small = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.BILINEAR)
    gray = _luma(small)
    metrics.update(
        decodable=True,
        width=width,
        height=height,
        brightness=round(float(gray.mean()), 2),
        sharpness=round(laplacian_variance(gray), 2),
        dhash=difference_hash(image),
    )
    return metrics
