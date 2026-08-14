"""Audit Lay's coverage in base + learned catalogs."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    data = json.loads((ROOT / "data" / "catalog.json").read_text(encoding="utf-8"))
    entries = data if isinstance(data, list) else data.get("products", [])
    lays: dict[str, int] = {}
    for e in entries:
        if (e.get("brand") or "").lower().startswith("lay"):
            pn = e.get("product_name") or ""
            lays[pn] = lays.get(pn, 0) + 1
    print(f"Base catalog Lay's product names: {len(lays)}")
    for name in sorted(lays):
        print(f"  - {name} ({lays[name]} embeddings)")

    needed = [
        "India's Magic Masala",
        "Tomato Tango",
        "American Style Cream",
        "Classic Salted",
    ]
    print("\nRack flavors vs catalog:")
    for flavor in needed:
        hit = any(flavor.lower().replace("'", "") in n.lower().replace("'", "") for n in lays)
        print(f"  - {flavor}: {'YES' if hit else 'MISSING from base catalog'}")

    learned_path = ROOT / "data" / "learned_catalog.json"
    if learned_path.exists():
        learned_data = json.loads(learned_path.read_text(encoding="utf-8"))
        learned = learned_data if isinstance(learned_data, list) else learned_data.get("products", [])
        lay_learned = [e for e in learned if "lay" in (e.get("brand") or "").lower()]
        print(f"\nLearned catalog Lay's-like entries: {len(lay_learned)}")
        for e in lay_learned[:15]:
            print(f"  - {e.get('brand')} | {e.get('product_name')} | {e.get('sku')}")


if __name__ == "__main__":
    main()
