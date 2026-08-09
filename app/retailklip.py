"""RetailKLIP: fine-tuned OpenCLIP visual encoder for Indian FMCG product matching."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
DEFAULT_CHECKPOINT = MODELS_DIR / "retailklip_vitb32.pt"
DEFAULT_META = MODELS_DIR / "retailklip_vitb32.json"

CLIP_MODEL_NAME = os.getenv("CLIP_MODEL_NAME", "ViT-B-32")
CLIP_PRETRAINED = os.getenv("CLIP_PRETRAINED", "laion2b_s34b_b79k")
USE_RETAILKLIP = os.getenv("USE_RETAILKLIP", "true").lower() in {"1", "true", "yes"}


def checkpoint_path() -> Path:
    override = os.getenv("RETAILKLIP_CHECKPOINT", "").strip()
    return Path(override) if override else DEFAULT_CHECKPOINT


def is_available() -> bool:
    return USE_RETAILKLIP and ensure_checkpoint().exists()


def ensure_checkpoint() -> Path:
    """Return checkpoint path, downloading from Supabase storage if missing locally."""
    path = checkpoint_path()
    meta = path.with_suffix(".json")
    if path.exists():
        return path
    try:
        from app.catalog_sync import download_retailklip_checkpoint

        if download_retailklip_checkpoint(path, meta):
            print(f"RetailKLIP downloaded from Supabase -> {path}")
    except Exception as exc:
        print(f"RetailKLIP download failed: {exc}")
    return path


def load_metadata() -> dict:
    meta_path = checkpoint_path().with_suffix(".json")
    if not meta_path.exists() and DEFAULT_META.exists():
        meta_path = DEFAULT_META
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as handle:
            return json.load(handle)
    return {}


def apply_checkpoint(model) -> bool:
    """Load fine-tuned visual weights into an open_clip model. Returns True on success."""
    path = ensure_checkpoint()
    if not USE_RETAILKLIP or not path.exists():
        return False
    import torch

    checkpoint = torch.load(path, map_location="cpu", weights_only=False)
    state = checkpoint.get("visual_state_dict") or checkpoint.get("state_dict")
    if not state:
        print(f"RetailKLIP checkpoint missing visual_state_dict: {path}")
        return False
    missing, unexpected = model.visual.load_state_dict(state, strict=False)
    if missing:
        print(f"RetailKLIP load: missing keys={len(missing)}")
    if unexpected:
        print(f"RetailKLIP load: unexpected keys={len(unexpected)}")
    meta = load_metadata()
    print(
        "RetailKLIP loaded:",
        path.name,
        f"epochs={checkpoint.get('epoch', meta.get('epoch', '?'))}",
        f"classes={checkpoint.get('num_classes', meta.get('num_classes', '?'))}",
    )
    return True
