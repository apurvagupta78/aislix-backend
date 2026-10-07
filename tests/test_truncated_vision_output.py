from types import SimpleNamespace

from app.make_scan import _coerce_json_object, _extract_json_object
from app.openai_vision_scan import _hit_output_limit


def _row(name: str, facings: int) -> str:
    return (
        '{"brand": "Brand", "product": "' + name + '", "actual_facings": ' + str(facings)
        + ', "bbox": {"x1": 1, "y1": 2, "x2": 3, "y2": 4}}'
    )


def test_cut_off_product_list_keeps_every_complete_row():
    text = (
        '{"shelf_analysis": {"products": ['
        + _row("A", 2) + ", " + _row("B", 3) + ", " + _row("C", 1)
        + ', {"brand": "Brand", "product": "D", "actual_fac'
    )
    out = _extract_json_object(text)
    assert out is not None
    assert [r["product"] for r in out["products"]] == ["A", "B", "C"]
    assert out["output_truncated"] is True


def test_complete_object_with_trailing_text_is_returned_whole():
    text = '{"products": [' + _row("A", 2) + "], " + '"executive_summary": "ok"} trailing note'
    out = _extract_json_object(text)
    assert out == {
        "products": [
            {"brand": "Brand", "product": "A", "actual_facings": 2, "bbox": {"x1": 1, "y1": 2, "x2": 3, "y2": 4}}
        ],
        "executive_summary": "ok",
    }


def test_coerce_uses_salvaged_rows_for_cut_off_text():
    text = '{"products": [' + _row("A", 2) + ", " + _row("B", 4) + ', {"brand": "X"'
    out = _coerce_json_object(text)
    assert len(out["products"]) == 2


def test_hit_output_limit_reads_incomplete_reason():
    cut = SimpleNamespace(status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens"))
    done = SimpleNamespace(status="completed", incomplete_details=None)
    filtered = SimpleNamespace(status="incomplete", incomplete_details=SimpleNamespace(reason="content_filter"))
    assert _hit_output_limit(cut) is True
    assert _hit_output_limit(done) is False
    assert _hit_output_limit(filtered) is False
