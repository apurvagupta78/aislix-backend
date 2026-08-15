"""Tests for retail SKU catalog + FAISS sync workflow."""

from __future__ import annotations

import json
from pathlib import Path

import faiss
import numpy as np
import pytest

from scripts import retail_sku, sync_faiss_orphans


@pytest.fixture()
def sku_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    catalog_path = tmp_path / "catalog.json"
    index_path = tmp_path / "faiss.index"

    products = [
        {
            "class_id": 1,
            "brand": "Sample",
            "product_name": "Deodorant Body Spray",
            "variant": "150 ml",
            "sku": "sample_deodorant_body_spray_150_ml",
            "category": "Personal Care",
        }
    ]
    catalog_path.write_text(
        json.dumps({"products": products}, indent=2) + "\n",
        encoding="utf-8",
    )

    vec = np.random.randn(512).astype(np.float32).reshape(1, -1)
    faiss.normalize_L2(vec)
    index = faiss.IndexFlatIP(512)
    index.add(vec)
    faiss.write_index(index, str(index_path))

    monkeypatch.setattr(retail_sku, "CATALOG_PATH", catalog_path)
    monkeypatch.setattr(retail_sku, "INDEX_PATH", index_path)
    monkeypatch.setattr(sync_faiss_orphans, "CATALOG_PATH", catalog_path)
    monkeypatch.setattr(sync_faiss_orphans, "INDEX_PATH", index_path)

    return catalog_path, index_path


def test_add_catalog_skus_appends_new_rows(sku_workspace):
    catalog_path, _ = sku_workspace
    added = retail_sku.add_catalog_skus(
        [
            {
                "brand": "Axe",
                "product_name": "Deodorant Body Spray",
                "variant": "150 ml",
                "sku": "axe_deodorant_body_spray_150_ml",
                "category": "Personal Care",
            }
        ]
    )
    assert added == ["axe_deodorant_body_spray_150_ml"]
    products = json.loads(catalog_path.read_text(encoding="utf-8"))["products"]
    assert len(products) == 2
    assert products[-1]["class_id"] == 2


def test_register_sku_hints_uses_donor_for_copy(sku_workspace):
    _, index_path = sku_workspace
    retail_sku.add_catalog_skus(
        [
            {
                "brand": "Axe",
                "product_name": "Deodorant Body Spray",
                "variant": "150 ml",
                "sku": "axe_deodorant_body_spray_150_ml",
                "category": "Personal Care",
                "donor_hint": "deodorant body spray",
            }
        ]
    )
    entry = {
        "sku": "axe_deodorant_body_spray_150_ml",
        "donor_hint": "deodorant body spray",
    }
    sync_faiss_orphans.register_sku_hints([entry])
    appended = sync_faiss_orphans.sync_orphan_embeddings("copy")
    assert appended == 1
    index = faiss.read_index(str(index_path))
    assert index.ntotal == 2


def test_add_retail_skus_catalog_and_faiss(sku_workspace):
    catalog_path, index_path = sku_workspace
    added, vectors = retail_sku.add_retail_skus(
        [
            {
                "brand": "Axe",
                "product_name": "Deodorant Body Spray",
                "variant": "150 ml",
                "sku": "axe_deodorant_body_spray_150_ml",
                "category": "Personal Care",
                "donor_hint": "deodorant body spray",
            }
        ],
        faiss_mode="copy",
    )
    assert added == ["axe_deodorant_body_spray_150_ml"]
    assert vectors == 1
    products = json.loads(catalog_path.read_text(encoding="utf-8"))["products"]
    index = faiss.read_index(str(index_path))
    assert len(products) == index.ntotal == 2


def test_sync_only_when_already_aligned(sku_workspace, capsys):
    appended = retail_sku.sync_faiss_orphans("copy")
    assert appended == 0
    assert "already aligned" in capsys.readouterr().out.lower()
