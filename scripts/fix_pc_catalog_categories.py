"""Re-tag misclassified personal care SKUs in catalog.json (Staples/Household -> Personal Care)."""

from __future__ import annotations

import json
import re
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "catalog.json"

PC_BRANDS = {
    "dove", "pantene", "sunsilk", "head", "tresemme", "clinic", "loreal", "l'oreal",
    "garnier", "indulekha", "himalaya", "clear", "meera", "schwarzkopf", "dabur",
    "colgate", "pepsodent", "sensodyne", "closeup", "lux", "lifebuoy", "dettol",
    "nivea", "mamaearth", "simple", "joy", "pears",
}

HAIR_KEYWORDS = re.compile(
    r"\b(shampoo|conditioner|hair|keratin|dandruff|anti[\-\s]?hair)\b",
    re.IGNORECASE,
)

WRONG_CATEGORIES = {"staples", "household", "general"}


def main() -> None:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    products = data if isinstance(data, list) else data.get("products", data)
    changed = 0
    for entry in products:
        brand = (entry.get("brand") or "").lower().strip()
        product = entry.get("product_name") or ""
        category = (entry.get("category") or "").lower().strip()
        if brand not in PC_BRANDS:
            continue
        if category not in WRONG_CATEGORIES:
            continue
        if not HAIR_KEYWORDS.search(product):
            continue
        entry["category"] = "Personal Care"
        changed += 1
    CATALOG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Updated {changed} catalog entries to Personal Care.")


if __name__ == "__main__":
    main()
