from app.astra_vision import (
    build_vision_prompt_text,
    extract_astra_analysis,
    inventory_from_astra_block,
    patch_parsed_for_astra_comparison,
    resolve_analysis_mode,
)


def test_resolve_analysis_mode_from_expected_products():
    mode = resolve_analysis_mode({"expected_products": [{"brand": "Colgate"}]})
    assert mode == "expected_products"


def test_resolve_analysis_mode_shelf_only_ignores_planogram_items():
    mode = resolve_analysis_mode(
        {
            "analysis_mode": "shelf_only",
            "planogram_items": [{"brand": "Lay's", "product_name": "Classic"}],
        }
    )
    assert mode == "shelf_only"


def test_build_vision_prompt_strips_preview_footer():
    prompt = build_vision_prompt_text(
        {"vision_prompt": "Analyze shelf\n---\nAislix payload preview\n- mode: x"}
    )
    assert prompt == "Analyze shelf"


def test_extract_expected_products_analysis():
    raw = {
        "operating_model": "supermarket",
        "image_quality": {"status": "GOOD", "reason": "clear"},
        "products": [
            {
                "location": "A1",
                "category": "Personal Care",
                "category_status": "MATCHED",
                "sub_category": "toothpaste",
                "subcategory_status": "MATCHED",
                "brand": "Colgate",
                "brand_status": "MATCHED",
                "product_name": "MaxFresh",
                "product_status": "MATCHED",
                "variant": "",
                "variant_status": "MATCHED",
                "expected_facings": 2,
                "actual_facings": 2,
                "facing_variance": 0,
                "facing_status": "MATCHED",
                "expected_shelf_units": 4,
                "actual_visible_units": 4,
                "shelf_unit_variance": 0,
                "shelf_unit_status": "MATCHED",
                "overall_status": "COMPLIANT",
                "confidence": 0.95,
                "evidence_note": "Visible on shelf",
            }
        ],
        "summary": {"total_products": 1},
    }
    key, block = extract_astra_analysis(raw, "expected_products")
    assert key == "astra_expected_products_analysis"
    assert block is not None
    assert len(block["products"]) == 1


def test_patch_parsed_rewrites_inventory_for_expected_products():
    parsed = {
        "is_full": False,
        "raw": {
            "products": [
                {
                    "brand": "Colgate",
                    "product_name": "MaxFresh",
                    "variant": "",
                    "category": "Personal Care",
                    "expected_facings": 2,
                    "actual_facings": 2,
                    "actual_visible_units": 4,
                    "product_status": "MATCHED",
                    "overall_status": "COMPLIANT",
                    "confidence": 0.9,
                }
            ],
            "summary": {"total_products": 1},
        },
        "inventory": None,
    }
    metadata = {
        "analysis_mode": "expected_products",
        "expected_products": [{"brand": "Colgate", "product_name": "MaxFresh"}],
    }
    patched, key, block = patch_parsed_for_astra_comparison(parsed, metadata)
    assert key == "astra_expected_products_analysis"
    assert block is not None
    assert len(patched["inventory"]) == 1
    assert patched["inventory"][0]["product_name"] == "MaxFresh"


def test_inventory_from_planogram_rows():
    rows = [
        {
            "location": "A1",
            "brand": "Lay's",
            "product_name": "Classic Salted",
            "variant": "",
            "actual_facings": 3,
            "actual_visible_units": 6,
            "overall_row_status": "COMPLIANT",
            "confidence": 0.88,
        }
    ]
    inventory = inventory_from_astra_block(
        "astra_planogram_analysis",
        {"rows": rows},
    )
    assert len(inventory) == 1
    assert inventory[0]["facings"] == 3
