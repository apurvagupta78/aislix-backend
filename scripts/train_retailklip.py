#!/usr/bin/env python3
"""Fine-tune OpenCLIP ViT-B-32 with ArcFace (RetailKLIP-style) on YOLO product crops."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.arcface_loss import ArcFaceLoss  # noqa: E402
from scripts.yolo_dataset import DEFAULT_DATASET, collect_class_crops  # noqa: E402

MODELS_DIR = ROOT / "models"
CHECKPOINT_PATH = MODELS_DIR / "retailklip_vitb32.pt"
META_PATH = MODELS_DIR / "retailklip_vitb32.json"


class CropDataset(Dataset):
    def __init__(self, samples: list[tuple[Image.Image, int]], preprocess):
        self.samples = samples
        self.preprocess = preprocess

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        image, label = self.samples[index]
        return self.preprocess(image), label


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RetailKLIP ArcFace fine-tuning")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--max-per-class", type=int, default=12)
    parser.add_argument("--max-classes", type=int, default=0, help="0 = all classes with crops")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--lr-decay", type=float, default=0.7, help="Block-wise LR decay factor")
    parser.add_argument("--output", type=Path, default=CHECKPOINT_PATH)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def _block_param_groups(model, base_lr: float, decay: float) -> list[dict]:
    """Block-wise learning rate decay on ViT visual trunk (RetailKLIP paper)."""
    visual = model.visual
    groups: list[dict] = []

    resblocks = getattr(getattr(visual, "transformer", None), "resblocks", None)
    if resblocks is not None:
        n_blocks = len(resblocks)
        block_param_ids: set[int] = set()
        for idx, block in enumerate(resblocks):
            depth_from_last = (n_blocks - 1) - idx
            lr = base_lr * (decay ** depth_from_last)
            groups.append({"params": block.parameters(), "lr": lr})
            block_param_ids.update(id(p) for p in block.parameters())
        other_params = [p for p in visual.parameters() if id(p) not in block_param_ids]
        if other_params:
            groups.append({"params": other_params, "lr": base_lr})
        return groups

    groups.append({"params": visual.parameters(), "lr": base_lr})
    return groups


def build_samples(
    by_class: dict[int, list[Image.Image]],
) -> tuple[list[tuple[Image.Image, int]], dict[int, int]]:
    class_ids = sorted(by_class.keys())
    id_map = {cid: idx for idx, cid in enumerate(class_ids)}
    samples: list[tuple[Image.Image, int]] = []
    for cid in class_ids:
        label = id_map[cid]
        for crop in by_class[cid]:
            samples.append((crop, label))
    random.shuffle(samples)
    return samples, id_map


def train(args: argparse.Namespace) -> None:
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    max_classes = args.max_classes if args.max_classes > 0 else None
    class_names, by_class = collect_class_crops(
        args.dataset,
        max_per_class=args.max_per_class,
        max_classes=max_classes,
    )
    if len(by_class) < 2:
        raise SystemExit("Need at least 2 classes with crops to fine-tune.")

    samples, id_map = build_samples(by_class)
    num_classes = len(id_map)
    print(f"Training RetailKLIP on {len(samples)} crops, {num_classes} classes")

    import open_clip

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32",
        pretrained="laion2b_s34b_b79k",
    )
    model.to(device)
    model.train()

    dataset = CropDataset(samples, preprocess)
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=0,
        pin_memory=device == "cuda",
    )

    embedding_size = 512
    arcface = ArcFaceLoss(num_classes=num_classes, embedding_size=embedding_size).to(device)
    param_groups = _block_param_groups(model, args.lr, args.lr_decay)
    param_groups.append({"params": arcface.parameters(), "lr": args.lr})
    optimizer = torch.optim.AdamW(param_groups, weight_decay=0.05)

    for epoch in range(1, args.epochs + 1):
        epoch_loss = 0.0
        steps = 0
        for images, labels in loader:
            images = images.to(device)
            labels = labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            embeddings = model.encode_image(images)
            embeddings = F.normalize(embeddings, dim=-1)
            loss = arcface(embeddings, labels)
            loss.backward()
            optimizer.step()
            epoch_loss += float(loss.item())
            steps += 1
            if steps % 25 == 0:
                print(f"  epoch {epoch} step {steps} loss={epoch_loss / steps:.4f}", flush=True)
        avg = epoch_loss / max(steps, 1)
        print(f"Epoch {epoch}/{args.epochs}  loss={avg:.4f}  steps={steps}", flush=True)

    model.eval()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "model_name": "ViT-B-32",
            "pretrained": "laion2b_s34b_b79k",
            "visual_state_dict": model.visual.state_dict(),
            "num_classes": num_classes,
            "epoch": args.epochs,
            "class_id_map": {str(k): v for k, v in id_map.items()},
        },
        args.output,
    )

    meta = {
        "model_name": "ViT-B-32",
        "pretrained": "laion2b_s34b_b79k",
        "num_classes": num_classes,
        "epoch": args.epochs,
        "samples": len(samples),
        "max_per_class": args.max_per_class,
        "method": "ArcFace (RetailKLIP-style)",
    }
    with open(META_PATH, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)

    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"Saved RetailKLIP checkpoint ({size_mb:.1f} MB) -> {args.output}")


if __name__ == "__main__":
    train(parse_args())
