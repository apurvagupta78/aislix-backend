from app.planogram_package import synthesize_planogram_package


def test_synthesize_from_product_rows():
    items = [
        {
            "sku": "COL-001",
            "brand": "Colgate",
            "product_name": "MaxFresh",
            "mrp_inr": 99,
            "shelf_position": "S1-L1",
            "expected_facings": 4,
        }
    ]
    pkg = synthesize_planogram_package(items, {})
    assert len(pkg["listed_skus"]) == 1
    assert len(pkg["assortment_skus"]) == 1
    assert len(pkg["price_requirements"]) == 1
    assert pkg["primary_brand"] == "Colgate"
