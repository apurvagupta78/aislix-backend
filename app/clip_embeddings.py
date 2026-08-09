"""Lazy-loaded CLIP / RetailKLIP embeddings."""

from __future__ import annotations

import os

import numpy as np
from PIL import Image

from app.retailklip import CLIP_MODEL_NAME, CLIP_PRETRAINED, apply_checkpoint

_model = None
_preprocess = None
_device = None
_using_retailklip = False
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "24"))


def _load_clip():
    global _model, _preprocess, _device, _using_retailklip
    if _model is not None:
        return _model, _preprocess, _device
    import open_clip
    import torch

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    _model, _, _preprocess = open_clip.create_model_and_transforms(
        CLIP_MODEL_NAME,
        pretrained=CLIP_PRETRAINED,
    )
    _using_retailklip = apply_checkpoint(_model)
    if not _using_retailklip:
        print(f"Using base OpenCLIP ({CLIP_MODEL_NAME}, {CLIP_PRETRAINED})")
    _model.to(_device)
    _model.eval()
    return _model, _preprocess, _device


def using_retailklip() -> bool:
    _load_clip()
    return _using_retailklip


def embed_pil_images(images: list[Image.Image]) -> np.ndarray:
    if not images:
        return np.zeros((0, 512), dtype=np.float32)
    import torch

    model, preprocess, device = _load_clip()
    chunks: list[np.ndarray] = []
    for start in range(0, len(images), EMBED_BATCH_SIZE):
        batch_imgs = images[start : start + EMBED_BATCH_SIZE]
        batch = torch.stack([preprocess(img) for img in batch_imgs]).to(device)
        with torch.no_grad():
            embeddings = model.encode_image(batch)
        embeddings = embeddings / embeddings.norm(dim=-1, keepdim=True)
        chunks.append(embeddings.cpu().numpy().astype(np.float32))
    return np.vstack(chunks)


def get_embeddings(image_paths: list[str]) -> np.ndarray:
    images = [Image.open(path).convert("RGB") for path in image_paths]
    return embed_pil_images(images)
