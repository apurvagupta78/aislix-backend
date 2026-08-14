"""Lay's chip variants exist in base catalog + FAISS."""

from __future__ import annotations

import json
from pathlib import Path

import faiss

ROOT = Path(__file__).resolve().parents[1]


def test_lays_tomato_and_cream_onion_in_catalog():
    raw = json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))
    products = raw["products"] if isinstance(raw, dict) else raw
    skus = {(p.get("sku") or "").lower() for p in products}
    assert "lays_tomato_tango_potato_chips" in skus
    assert "lays_american_style_cream_and_onion_potato_chips" in skus


def test_lays_variants_have_reference_embeddings():
    raw = json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))
    products = raw["products"] if isinstance(raw, dict) else raw
    tomato = sum(1 for p in products if p.get("sku") == "lays_tomato_tango_potato_chips")
    cream = sum(
        1 for p in products if p.get("sku") == "lays_american_style_cream_and_onion_potato_chips"
    )
    assert tomato >= 10
    assert cream >= 10
    index = faiss.read_index(str(ROOT / "data" / "faiss.index"))
    assert index.ntotal >= 6377
