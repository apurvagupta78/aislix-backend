import io

from app import document_reader as dr


def _invoice_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import PageBreak, SimpleDocTemplate, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    style = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0))])
    page1 = Table(
        [
            ["S.No", "Item Description", "Qty", "Rate", "Amount"],
            ["1", "Amul Butter 500g", "24", "275.00", "6600.00"],
            ["2", "Tata Salt 1kg", "40", "28.00", "1120.00"],
        ]
    )
    page2 = Table([["3", "Maggi Noodles 70g", "120", "14.00", "1680.00"]])
    page1.setStyle(style)
    page2.setStyle(style)
    doc.build([page1, PageBreak(), page2, PageBreak(), Table([[" "]])])
    return buf.getvalue()


def test_split_header_finds_header_and_reuses_it_on_continuation_pages():
    headers, rows, found = dr.split_header([["Item", "Qty", "Rate"], ["Soap", "2", "30"]], None)
    assert found and headers == ["Item", "Qty", "Rate"] and rows == [["Soap", "2", "30"]]
    headers, rows, found = dr.split_header([["Shampoo", "1", "120"]], headers)
    assert not found and headers == ["Item", "Qty", "Rate"] and rows == [["Shampoo", "1", "120"]]


def test_parse_markdown_and_html_tables():
    md = "Invoice\n| Item | Qty |\n|---|---|\n| Soap | 2 |\n\nTotal"
    assert dr.parse_markdown_tables(md) == [[["Item", "Qty"], ["Soap", "2"]]]
    html = "<table><tr><th>Item</th><th>Qty</th></tr><tr><td>Soap</td><td>2</td></tr></table>"
    assert dr.parse_html_tables(html) == [[["Item", "Qty"], ["Soap", "2"]]]


def test_page_ranges():
    assert dr.page_ranges([5, 1, 2, 3, 9]) == "1-3,5,9"


def test_parse_azure_invoice_groups_items_by_page():
    result = {
        "documents": [
            {
                "fields": {
                    "VendorName": {"type": "string", "valueString": "Hindustan Foods"},
                    "InvoiceTotal": {"type": "currency", "valueCurrency": {"amount": 100.0, "currencyCode": "INR"}},
                    "Items": {
                        "valueArray": [
                            {
                                "confidence": 0.93,
                                "boundingRegions": [{"pageNumber": 2}],
                                "valueObject": {
                                    "Description": {"type": "string", "valueString": "Soap"},
                                    "Quantity": {"type": "number", "valueNumber": 2.0},
                                    "UnitPrice": {"type": "currency", "valueCurrency": {"amount": 50.0}},
                                    "Amount": {"type": "currency", "valueCurrency": {"amount": 100.0}},
                                },
                            }
                        ]
                    },
                }
            }
        ]
    }
    tables, meta = dr.parse_azure_invoice(result)
    assert meta["supplier_name"] == "Hindustan Foods" and meta["currency"] == "INR"
    table = tables[2][0]
    assert table["headers"] == ["Product code", "Description", "Quantity", "Unit", "Unit price", "Amount"]
    assert table["rows"] == [["", "Soap", "2", "", "50", "100"]]
    assert table["confidence"] == [0.93]


def test_run_reads_text_layer_and_marks_scanned_pages(monkeypatch):
    pdf = _invoice_pdf()
    monkeypatch.setattr(dr, "_download", lambda url: pdf)
    monkeypatch.setenv("DOCUMENT_OCR_PROVIDER", "none")
    job = "test-job"
    dr._jobs[job] = {"status": "processing", "created_at": 0}
    result = dr._run(job, "https://example.test/doc.pdf", "application/pdf")

    assert result["pages_total"] == 3 and result["provider"] == "none"
    page1, page2, page3 = result["pages"]
    assert page1["source"] == "text"
    assert page1["tables"][0]["headers"] == ["S.No", "Item Description", "Qty", "Rate", "Amount"]
    assert page1["tables"][0]["rows"][0] == ["1", "Amul Butter 500g", "24", "275.00", "6600.00"]
    assert page2["tables"][0]["headers"] == page1["tables"][0]["headers"]
    assert page2["tables"][0]["rows"] == [["3", "Maggi Noodles 70g", "120", "14.00", "1680.00"]]
    assert page3["source"] == "none" and result["scanned_pages"] == 1

    image = dr.render_page_jpeg(job, 3)
    assert image and image[:2] == b"\xff\xd8"
    dr._jobs.pop(job, None)
