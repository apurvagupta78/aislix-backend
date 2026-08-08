"""Lazy-loaded CLIP embeddings."""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image

_model = None
_preprocess = None
_device = None


def _load_clip():
    global _model, _preprocess, _device
    if _model is not None:
        return _model, _preprocess, _device
    import open_clip

    _device = "cuda" if torch.cuda.is_available() else "cpu"
    _model, _, _preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32",
        pretrained="laion2b_s34b_b79k",
    )
    _model.to(_device)
    _model.eval()
    return _model, _preprocess, _device


def embed_pil_images(images: list[Image.Image]) -> np.ndarray:
    if not images:
        return np.zeros((0, 512), dtype=np.float32)
    model, preprocess, device = _load_clip()
    batch = torch.stack([preprocess(img) for img in images]).to(device)
    with torch.no_grad():
        embeddings = model.encode_image(batch)
    embeddings = embeddings / embeddings.norm(dim=-1, keepdim=True)
    return embeddings.cpu().numpy().astype(np.float32)


def get_embeddings(image_paths: list[str]) -> np.ndarray:
    images = [Image.open(path).convert("RGB") for path in image_paths]
    return embed_pil_images(images)
