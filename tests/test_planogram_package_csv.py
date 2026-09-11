"""Tests for planogram audit package CSV parsers."""

from app.planogram_package_csv import parse_assortment_csv, parse_prices_csv, parse_promotions_csv, template_csv


def test_assortment_template():
    payload = template_csv("assortment")
    assert "sku" in payload["csv_text"]
    assert "mandatory_assortment" in payload["csv_text"]


def test_parse_assortment_valid():
    csv_text = template_csv("assortment")["csv_text"]
    result = parse_assortment_csv(csv_text)
    assert result["valid_count"] >= 1
    assert not result["errors"]


def test_parse_prices_valid():
    csv_text = template_csv("prices")["csv_text"]
    result = parse_prices_csv(csv_text)
    assert result["valid_count"] >= 1


def test_parse_promotions_valid():
    csv_text = template_csv("promotions")["csv_text"]
    result = parse_promotions_csv(csv_text)
    assert result["valid_count"] >= 1
