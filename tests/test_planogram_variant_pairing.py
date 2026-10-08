"""Document lines must not pair with a different named flavour of the same brand."""

from app.planogram_match import join_planogram_with_cv


def _cv(brand, product, variant, facings=4):
    return {
        "brand": brand,
        "brand_status": "IDENTIFIED",
        "product_name": product,
        "product_status": "IDENTIFIED",
        "variant": variant,
        "variant_status": "IDENTIFIED",
        "actual_facings": facings,
        "actual_visible_units": facings,
    }


def _line(brand, product):
    return {"brand": brand, "product_name": product, "variant": None, "expected_qty": 1}


def test_flavour_in_product_name_does_not_pair_with_other_flavour():
    lines = [
        _line("Trident", "Trident Spearmint Sugar Free Gum"),
        _line("Trident", "Trident Peppermint Sugar Free Gum"),
        _line("Trident", "Trident Watermelon Twist Gum"),
        _line("Trident", "Trident Tropical Twist Gum"),
        _line("Texas", "Texas Apple Candy"),
        _line("Texas", "Texas Strawberry Candy"),
        _line("Texas", "Texas Mixed Drops Candy"),
    ]
    shelf = [
        _cv("Trident", "Sugar Free Gum", "Spearmint"),
        _cv("Trident", "Sugar Free Gum", "Peppermint"),
        _cv("Trident", "Sugar Free Gum", "Watermelon Twist"),
        _cv("Trident", "Sugar Free Gum", "Cinnamon"),
        _cv("Texass", "Cola Candy", "Cola"),
        _cv("Texass", "Strawberry Candy", "Strawberry"),
        _cv("Texass", "Mixed Drops", "Mixed Drops"),
    ]
    rows, unplanned = join_planogram_with_cv(lines, shelf)
    by_name = {r["product_name"]: r for r in rows}

    assert by_name["Trident Spearmint Sugar Free Gum"]["actual_variant"] == "Spearmint"
    assert by_name["Trident Peppermint Sugar Free Gum"]["actual_variant"] == "Peppermint"
    assert by_name["Trident Watermelon Twist Gum"]["actual_variant"] == "Watermelon Twist"
    assert by_name["Texas Strawberry Candy"]["actual_variant"] == "Strawberry"
    assert by_name["Texas Mixed Drops Candy"]["actual_variant"] == "Mixed Drops"

    for missing in ("Trident Tropical Twist Gum", "Texas Apple Candy"):
        assert by_name[missing]["source_actual"] is None
        assert by_name[missing]["match_status"] == "NOT_FOUND"
    assert {u["variant"] for u in unplanned} == {"Cinnamon", "Cola"}


def test_best_pair_wins_regardless_of_line_order():
    lines = [
        _line("Oreo", "Oreo Biscuits"),
        _line("Oreo", "Oreo Chocolate Cream Biscuits"),
    ]
    shelf = [_cv("Oreo", "Oreo Biscuits", "Chocolate Cream"), _cv("Oreo", "Oreo Biscuits", "Vanilla")]
    rows, unplanned = join_planogram_with_cv(lines, shelf)
    by_name = {r["product_name"]: r for r in rows}
    assert by_name["Oreo Chocolate Cream Biscuits"]["actual_variant"] == "Chocolate Cream"
    assert by_name["Oreo Biscuits"]["actual_variant"] == "Vanilla"
    assert unplanned == []


def test_single_brand_line_still_matches_named_variant():
    rows, unplanned = join_planogram_with_cv([_line("Rolo", "Rolo Chocolate 24 pack")], [_cv("Rolo", "Rolo", "Caramel")])
    assert rows[0]["source_actual"] == "astra"
    assert unplanned == []
