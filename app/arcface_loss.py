"""Lightweight ArcFace loss for RetailKLIP fine-tuning (no scipy dependency)."""

from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F


class ArcFaceLoss(nn.Module):
    def __init__(
        self,
        num_classes: int,
        embedding_size: int = 512,
        margin: float = 0.35,
        scale: float = 30.0,
    ):
        super().__init__()
        self.num_classes = num_classes
        self.embedding_size = embedding_size
        self.margin = margin
        self.scale = scale
        self.weight = nn.Parameter(torch.empty(num_classes, embedding_size))
        nn.init.xavier_uniform_(self.weight)

        self.cos_m = math.cos(margin)
        self.sin_m = math.sin(margin)
        self.th = math.cos(math.pi - margin)
        self.mm = math.sin(math.pi - margin) * margin

    def forward(self, embeddings: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
        embeddings = F.normalize(embeddings)
        weights = F.normalize(self.weight)
        cosine = F.linear(embeddings, weights)
        sine = torch.sqrt((1.0 - torch.clamp(cosine.pow(2), 0.0, 1.0)))
        phi = cosine * self.cos_m - sine * self.sin_m
        phi = torch.where(cosine > self.th, phi, cosine - self.mm)
        one_hot = F.one_hot(labels, num_classes=self.num_classes).to(cosine.dtype)
        logits = one_hot * phi + (1.0 - one_hot) * cosine
        return F.cross_entropy(logits * self.scale, labels)
