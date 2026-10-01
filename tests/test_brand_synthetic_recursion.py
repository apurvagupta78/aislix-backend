"""Synthetic brand labels must never re-enter match_product_for_brand (RecursionError)."""

from app import brand_dictionary
from app.brand_dictionary import _synthetic_brand_product, match_product_for_brand
from app.scan_context import resolve_scan_context

_FACE_WASH_ONLY = [
    {"brand": "Acme", "product_name": "Neem Face Wash", "variant": "50 ml", "sku": "acme_neem_face_wash_50_ml"},
    {"brand": "Acme", "product_name": "Lemon Face Wash", "variant": "100 ml", "sku": "acme_lemon_face_wash_100_ml"},
]


def _multi_category_context() -> dict:
    return resolve_scan_context(
        {
            "category": "Baby & Pet Care",
            "sub_category": "Baby food",
            "category_selections": [
                {"category_name": "Baby & Pet Care", "sub_category_id": "Baby food"},
                {"category_name": "Baby & Pet Care", "sub_category_id": "diapers"},
                {"category_name": "Baby & Pet Care", "sub_category_id": "wipes"},
            ],
        }
    )


def test_multi_category_audit_brand_without_typed_sku_returns_synthetic_label(monkeypatch):
    monkeypatch.setattr(brand_dictionary, "products_for_brand", lambda brand: list(_FACE_WASH_ONLY))
    ctx = _multi_category_context()
    assert ctx["multi_sub_category_audit"] is True

    product = match_product_for_brand("Acme", "Acme deodorant body spray", scan_context=ctx)

    assert product is not None
    assert product["product_name"] == "Deodorant Body Spray"
    assert product["brand"]


def test_synthetic_shampoo_label_does_not_recurse_when_catalog_lacks_it(monkeypatch):
    monkeypatch.setattr(brand_dictionary, "products_for_brand", lambda brand: list(_FACE_WASH_ONLY))

    product = _synthetic_brand_product("Nivea", "nivea men", {"sub_category": "shampoo"})

    assert product is not None
    assert product["product_name"] == "Men Strong Power Shampoo"
