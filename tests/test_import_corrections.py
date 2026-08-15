"""Tests for correction import into benchmark manifest."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.import_corrections_to_manifest import import_corrections


def test_import_corrections_adds_facing(tmp_path: Path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "cases": [
                    {
                        "id": "tea_a1s",
                        "category": "Beverages · Tea",
                        "sub_category": "tea",
                        "image": "images/tea_a1s.jpg",
                        "facings": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    corrections_path = tmp_path / "corrections.json"
    corrections_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "queue_id": "q1",
                        "brand": "Lipton",
                        "product_name": "Green Tea",
                        "ocr_label": "Lipton Green Tea 25 tea bags",
                        "box": [10, 20, 90, 200],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    stats = import_corrections(manifest_path, corrections_path, case_id="tea_a1s", create_case=False)
    assert stats["added"] == 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["cases"][0]["facings"][0]["brand"] == "Lipton"
