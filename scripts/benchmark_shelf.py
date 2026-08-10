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

    result = run_ocr_benchmark(GOLDEN_OCR_CASES)
    print(json.dumps(result, indent=2))
    if result["accuracy_pct"] < args.min_accuracy:
        print(f"FAIL: accuracy {result['accuracy_pct']}% < {args.min_accuracy}%")
        sys.exit(1)
    mixed = run_ocr_benchmark(MIXED_SHELF_OCR_CASES)
    print(json.dumps(mixed, indent=2))
    if mixed["accuracy_pct"] < args.min_accuracy:
        print(f"FAIL mixed shelf: {mixed['accuracy_pct']}% < {args.min_accuracy}%")
        sys.exit(1)
    print(f"PASS: shampoo {result['accuracy_pct']}% mixed {mixed['accuracy_pct']}% >= {args.min_accuracy}%")


if __name__ == "__main__":
    main()
