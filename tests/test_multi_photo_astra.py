from app.multi_photo_astra import merge_astra_photo_payloads


def _photo(products, *, quality="GOOD", labels=None):
    return {
        "analysis_type": "shelf_cv",
        "image_quality": quality,
        "products": products,
        "location_labels": labels or [],
        "summary": {
            "products_detected": len(products),
            "total_actual_facings": sum(p["actual_facings"] for p in products),
            "total_actual_visible_units": sum(p["actual_visible_units"] for p in products),
            "prices_read": 0,
        },
    }


def test_single_photo_is_unchanged():
    one = _photo([{"brand": "A", "product": "X", "actual_facings": 2, "actual_visible_units": 2}])
    assert merge_astra_photo_payloads([one]) is one


def test_merges_products_and_sums_totals():
    p1 = _photo(
        [{"brand": "Colgate", "product": "Strong Teeth", "variant": "100g", "actual_facings": 3, "actual_visible_units": 3}],
        labels=[{"label": "A1", "status": "READ"}],
    )
    p2 = _photo(
        [
            {"brand": "Colgate", "product": "Strong Teeth", "variant": "100g", "actual_facings": 2, "actual_visible_units": 1},
            {"brand": "Pepsodent", "product": "Germicheck", "variant": "", "actual_facings": 4, "actual_visible_units": 4},
        ],
        quality="LIMITED",
        labels=[{"label": "A1", "status": "READ"}, {"label": "A2", "status": "READ"}],
    )
    merged = merge_astra_photo_payloads([p1, p2])

    assert len(merged["products"]) == 3
    assert [p["photo_index"] for p in merged["products"]] == [1, 2, 2]
    assert merged["summary"]["total_actual_facings"] == 9
    assert merged["summary"]["total_actual_visible_units"] == 8
    assert merged["summary"]["products_detected"] == 2
    assert merged["summary"]["brands_detected"] == 2
    assert merged["summary"]["location_labels_read"] == 2
    assert merged["image_quality"] == "LIMITED"
    assert merged["multi_photo"] == {"photo_count": 2, "facings_per_photo": [3, 6], "merged_facings": 9}


def test_non_shelf_cv_payload_falls_back_to_first_photo():
    first = {"analysis_type": "other"}
    assert merge_astra_photo_payloads([first, {"products": []}]) is first


def test_missing_summary_total_is_not_faked():
    p1 = _photo([{"brand": "A", "product": "X", "actual_facings": 1, "actual_visible_units": 1}])
    p2 = _photo([{"brand": "B", "product": "Y", "actual_facings": 1, "actual_visible_units": 1}])
    del p2["summary"]["total_actual_visible_units"]
    merged = merge_astra_photo_payloads([p1, p2])
    assert "total_actual_visible_units" not in merged["summary"]
    assert merged["summary"]["total_actual_facings"] == 2
