"""Tests for accuracy benchmark helpers."""

from __future__ import annotations

from app.accuracy_benchmark import (
    brand_match,
    character_error_rate,
    product_match,
    resolve_facing_box,
)


def test_character_error_rate_exact_and_typo():
    assert character_error_rate("lays magic masala", "lays magic masala") == 0.0
    assert 0.0 < character_error_rate("lays magic masala", "lays magc masala") < 0.2


def test_resolve_facing_box_normalized():
    box = resolve_facing_box({"box": [0.1, 0.2, 0.3, 0.4]}, 1000, 500)
    assert box == [100, 100, 300, 200]


def test_brand_and_product_match():
    assert brand_match("Lays", "Lay's")
    assert product_match("Tomato Tango Potato Chips", "Tomato Tango")
