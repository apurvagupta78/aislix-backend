import torch
import open_clip
import numpy as np
from PIL import Image

device = "cuda" if torch.cuda.is_available() else "cpu"

model, _, preprocess = open_clip.create_model_and_transforms(
    "ViT-B-32",
    pretrained="laion2b_s34b_b79k",
)
model.to(device)
model.eval()


def embed_pil_images(images: list[Image.Image]) -> np.ndarray:
    if not images:
        return np.zeros((0, 512), dtype=np.float32)
    batch = torch.stack([preprocess(img) for img in images]).to(device)
    with torch.no_grad():
        embeddings = model.encode_image(batch)
    embeddings = embeddings / embeddings.norm(dim=-1, keepdim=True)
    return embeddings.cpu().numpy().astype(np.float32)


def get_embeddings(image_paths: list[str]) -> np.ndarray:
    images = [Image.open(path).convert("RGB") for path in image_paths]
    return embed_pil_images(images)
