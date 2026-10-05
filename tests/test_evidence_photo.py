import io

import numpy as np
from PIL import Image, ImageFilter

from app.evidence_photo import difference_hash, photo_metrics


def _jpeg(image: Image.Image, exif: Image.Exif | None = None) -> bytes:
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=92, **({"exif": exif} if exif else {}))
    return out.getvalue()


def _checkerboard(size: int = 640, cell: int = 8) -> Image.Image:
    grid = (np.indices((size, size)) // cell).sum(axis=0) % 2
    return Image.fromarray((grid * 255).astype(np.uint8)).convert("RGB")


def test_sharp_photo_has_more_detail_than_blurred():
    sharp = photo_metrics(_jpeg(_checkerboard()))
    blurred = photo_metrics(_jpeg(_checkerboard().filter(ImageFilter.GaussianBlur(12))))
    assert sharp["decodable"] and blurred["decodable"]
    assert sharp["sharpness"] > 1000
    assert blurred["sharpness"] < 45


def test_brightness_of_dark_and_white_photos():
    assert photo_metrics(_jpeg(Image.new("RGB", (640, 480), (5, 5, 5))))["brightness"] < 35
    assert photo_metrics(_jpeg(Image.new("RGB", (640, 480), (255, 255, 255))))["brightness"] > 245


def test_reads_capture_time_and_offset_from_exif():
    exif = Image.Exif()
    exif[0x0132] = "2026:10:05 10:00:00"
    sub = exif.get_ifd(0x8769)
    sub[0x9003] = "2026:10:05 11:24:04"
    sub[0x9011] = "+05:30"
    metrics = photo_metrics(_jpeg(Image.new("RGB", (640, 480), (120, 130, 140)), exif))
    assert metrics["exif_taken_at"] == "2026:10:05 11:24:04"
    assert metrics["exif_offset"] == "+05:30"


def test_photo_without_exif_has_no_capture_time():
    metrics = photo_metrics(_jpeg(Image.new("RGB", (640, 480), (120, 130, 140))))
    assert metrics["exif_taken_at"] is None and metrics["exif_offset"] is None
    assert metrics["width"] == 640 and metrics["height"] == 480


def test_same_scene_resaved_keeps_a_close_fingerprint():
    base = _checkerboard(cell=80)
    a = int(difference_hash(base), 16)
    b = int(difference_hash(base.resize((600, 600)).filter(ImageFilter.GaussianBlur(1))), 16)
    assert bin(a ^ b).count("1") <= 5


def test_unreadable_file_still_gets_a_fingerprint():
    metrics = photo_metrics(b"not an image at all")
    assert metrics["decodable"] is False
    assert len(metrics["sha256"]) == 64
