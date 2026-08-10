"""Benchmark recognition accuracy on labeled shelf test cases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.brand_dictionary import match_from_text  # noqa: E402

# OCR text samples from clear shampoo-row golden case (Aug 10 scan).
GOLDEN_OCR_CASES = [
    ("Dove Intense Repair Shampoo 180ml", "Dove"),
    ("Head & Shoulders Classic Clean Shampoo 180ml", "Head"),
    ("Sunsilk Long Healthy Growth Shampoo 180ml", "Sunsilk"),
    ("Pantene Hair Fall Control Shampoo 180ml", "Pantene"),
    ("Tresemme Smooth Shine Shampoo 185ml", "Tresemme"),
    ("L'Oreal Paris Total Repair 5 Shampoo 180ml", "Loreal"),
    ("Himalaya Anti Hair Fall Shampoo 180ml", "Himalaya"),
    ("Clinic Plus Strong and Long Shampoo 180ml", "Clinic"),
]

MIXED_SHELF_OCR_CASES = [
    ("Pears Pure and Gentle Soap 125g", "Pears"),
    ("Dettol Original Hand Wash 200ml", "Dettol"),
    ("Smooth and Shine blue bottle Tresemme", "Tresemme"),
    ("Himalaya Anti Hair Fall Shampoo 180ml", "Himalaya"),
    ("Keratin Smooth Shampoo 185ml Tresemme", "Tresemme"),
    ("Simple Kind To Skin Refreshing Facial Wash", "Simple"),
    ("Dettol hand wash original 200 ml", "Dettol"),
]

TEA_ROW_OCR_CASES = [
    ("Lipton Green Tea 25 tea bags", "Lipton"),
    ("Tetley Green Tea 100g", "Tetley"),
    ("Tata Tea Agni Strong Leaf Tea 250g", "Tata"),
    ("Brooke Bond Red Label Natural Care Tea", "Brooke"),
    ("Taj Mahal Rich and Flavourful Tea", "Taj"),
]

SNACK_ROW_OCR_CASES = [
    ("Britannia Good Day Butter Cookies 200g", "Britannia"),
    ("Haldiram Bhujia Sev 200g", "Haldiram"),
    ("Parle-G Glucose Biscuits 250g", "Parle"),
    ("Maggi 2 Minute Masala Noodles 70g", "Maggi"),
    ("Lay's Classic Salted Potato Chips 52g", "Lays"),
]

HOME_CARE_OCR_CASES = [
    ("Surf Excel Easy Wash Detergent Powder 1kg", "Surf"),
    ("Harpic Power Plus Toilet Cleaner 500ml", "Harpic"),
    ("Vim Dishwash Liquid Lemon 500ml", "Vim"),
]

GROCERY_OCR_CASES = [
    ("Aashirvaad Shudh Chakki Atta 5kg", "Aashirvaad"),
    ("Fortune Soya Health Refined Oil 1L", "Fortune"),
]

ALL_BENCHMARKS = [
    ("Shampoo row", GOLDEN_OCR_CASES),
    ("Mixed PC shelf", MIXED_SHELF_OCR_CASES),
    ("Tea row", TEA_ROW_OCR_CASES),
    ("Snack row", SNACK_ROW_OCR_CASES),
    ("Home care", HOME_CARE_OCR_CASES),
    ("Grocery staples", GROCERY_OCR_CASES),
]


def _brand_matches(expected: str, actual: str) -> bool:
    exp = expected.lower().strip()
    act = actual.lower().strip()
    if exp == act or exp in act or act in exp:
        return True
    if exp == "head" and "head" in act:
        return True
    if exp == "loreal" and "loreal" in act.replace("'", ""):
        return True
    if exp == "parle" and "parle" in act:
        return True
    if exp == "surf" and "surf" in act:
        return True
    return False


def run_ocr_benchmark(cases: list[tuple[str, str]] | None = None) -> dict:
    cases = cases or GOLDEN_OCR_CASES
    correct = 0
    failures: list[dict] = []
    for text, expected_brand in cases:
        match = match_from_text(text)
        if match and _brand_matches(expected_brand, match.get("brand") or ""):
            correct += 1
        else:
            failures.append(
                {
                    "text": text,
                    "expected": expected_brand,
                    "got": (match or {}).get("brand"),
                }
            )
    total = len(cases)
    accuracy = correct / total if total else 0.0
    return {
        "total": total,
        "correct": correct,
        "accuracy_pct": round(accuracy * 100, 1),
        "failures": failures,
    }


def run_all_benchmarks(min_accuracy: float) -> int:
    shampoo = run_ocr_benchmark(GOLDEN_OCR_CASES)
    mixed = run_ocr_benchmark(MIXED_SHELF_OCR_CASES)
    print("Shampoo row:", json.dumps(shampoo, indent=2))
    print("Mixed shelf:", json.dumps(mixed, indent=2))
    failed = 0
    for name, result in [("Shampoo row", shampoo), ("Mixed shelf", mixed)]:
        if result["accuracy_pct"] < min_accuracy:
            print(f"FAIL {name}: {result['accuracy_pct']}% < {min_accuracy}%")
            failed = 1
        else:
            print(f"PASS {name}: {result['accuracy_pct']}% >= {min_accuracy}%")
    return failed


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark shelf recognition accuracy.")
    parser.add_argument("--min-accuracy", type=float, default=95.0, help="Minimum accuracy percent to pass.")
    args = parser.parse_args()

    failed = 0
    for name, cases in ALL_BENCHMARKS:
        result = run_ocr_benchmark(cases)
        print(f"{name}:", json.dumps(result, indent=2))
        if result["accuracy_pct"] < args.min_accuracy:
            print(f"FAIL {name}: {result['accuracy_pct']}% < {args.min_accuracy}%")
            failed = 1
        else:
            print(f"PASS {name}: {result['accuracy_pct']}% >= {args.min_accuracy}%")
    sys.exit(failed)


if __name__ == "__main__":
    main()
