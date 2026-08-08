import numpy as np
from sklearn.cluster import DBSCAN

from app.clip_embeddings import get_embeddings


def group_similar_products(records, threshold=0.90):
    if not records:
        return []
    image_paths = [record["image_path"] for record in records]
    embeddings = get_embeddings(image_paths)
    clustering = DBSCAN(eps=1 - threshold, min_samples=1, metric="cosine")
    labels = clustering.fit_predict(embeddings)
    groups: dict[int, list] = {}
    for label, record in zip(labels, records):
        groups.setdefault(int(label), []).append(record)
    return list(groups.values())
