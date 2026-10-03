"""Large reference documents (invoice / stock list PDFs and photos) -> per-page tables.

Digital PDF pages are read from their own text layer (free, exact). Only scanned or
photographed pages go to a paid OCR provider (Azure Document Intelligence prebuilt-invoice
or Mistral OCR, chosen by env). Pages no provider could read are returned with
source "none" so the caller can have Luna re-read just those pages.

Jobs live in memory (single-replica Railway deployment), like app.jobs.
"""

from __future__ import annotations

import io
import os
import re
import threading
import time
import traceback
import uuid
from typing import Any

import requests

MAX_DOCUMENT_BYTES = 80 * 1024 * 1024
MAX_PAGES = 600
TEXT_PAGE_MIN_CHARS = 30
JOB_TTL_SECONDS = 2 * 60 * 60
PAGE_RENDER_DPI = 170
MISTRAL_PAGES_PER_CALL = 50

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}

HEADER_WORDS = re.compile(
    r"\b(qty|quantity|rate|price|mrp|amount|description|item|product|particulars|hsn|uom|unit|"
    r"sku|code|brand|pack|size|s\.?\s?no|sl\.?\s?no|sr\.?\s?no|total|value|location|bin|barcode|ean)\b",
    re.I,
)
NUMERIC_CELL = re.compile(r"^[\s₹$€£(),.%/+-]*\d[\d\s,./()%:+-]*$")


# --------------------------------------------------------------------------- tables


def _clean_cell(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _is_numeric(cell: str) -> bool:
    return bool(cell) and bool(NUMERIC_CELL.match(cell))


def _looks_like_header(cells: list[str]) -> bool:
    filled = [c for c in cells if c]
    if len(filled) < 2:
        return False
    if any(_is_numeric(c) for c in filled):
        return False
    return sum(1 for c in filled if HEADER_WORDS.search(c)) >= 1


def split_header(rows: list[list[str]], previous_header: list[str] | None) -> tuple[list[str], list[list[str]], bool]:
    """Return (headers, data_rows, header_found). Continuation pages reuse the previous header."""
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        return [], [], False
    for index, row in enumerate(rows[:5]):
        if _looks_like_header(row):
            headers = [c or f"Column {i + 1}" for i, c in enumerate(row)]
            return headers, rows[index + 1 :], True
    width = max(len(r) for r in rows)
    if previous_header and len(previous_header) == width:
        return list(previous_header), rows, False
    return [f"Column {i + 1}" for i in range(width)], rows, False


def parse_markdown_tables(markdown: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in (markdown or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.count("|") >= 2:
            cells = [_clean_cell(c) for c in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) or c == "" for c in cells):
                continue
            current.append(cells)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def parse_html_tables(html: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    for table_html in re.findall(r"<table.*?</table>", html or "", flags=re.S | re.I):
        rows = []
        for row_html in re.findall(r"<tr.*?</tr>", table_html, flags=re.S | re.I):
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.S | re.I)
            rows.append([_clean_cell(re.sub(r"<[^>]+>", " ", c)) for c in cells])
        if rows:
            tables.append(rows)
    return tables


def _tables_from_raw(raw_tables: list[list[list[str]]], previous_header: list[str] | None):
    out = []
    header = previous_header
    for raw in raw_tables:
        rows = [[_clean_cell(c) for c in row] for row in raw]
        rows = [r for r in rows if any(r)]
        if len(rows) < 1 or max(len(r) for r in rows) < 2:
            continue
        headers, data, found = split_header(rows, header)
        if not data:
            continue
        width = len(headers)
        data = [(r + [""] * width)[:width] for r in data]
        out.append({"headers": headers, "rows": data, "confidence": None})
        if found:
            header = headers
    return out, header


# --------------------------------------------------------------------------- text layer


def _text_layer_tables(page) -> list[list[list[str]]]:
    tables = page.extract_tables() or []
    usable = [t for t in tables if t and max(len(r) for r in t) >= 2]
    if usable:
        return usable
    tables = page.extract_tables({"vertical_strategy": "text", "horizontal_strategy": "text"}) or []
    return [t for t in tables if len(t) >= 2 and max(len(r) for r in t) >= 3]


# --------------------------------------------------------------------------- OCR providers


def ocr_provider() -> str:
    requested = (os.getenv("DOCUMENT_OCR_PROVIDER") or "auto").strip().lower()
    has_azure = bool(os.getenv("AZURE_DI_ENDPOINT") and os.getenv("AZURE_DI_KEY"))
    has_mistral = bool(os.getenv("MISTRAL_API_KEY"))
    if requested == "azure":
        return "azure" if has_azure else "none"
    if requested == "mistral":
        return "mistral" if has_mistral else "none"
    if requested == "none":
        return "none"
    if has_azure:
        return "azure"
    if has_mistral:
        return "mistral"
    return "none"


def page_ranges(pages: list[int]) -> str:
    pages = sorted(set(pages))
    parts: list[str] = []
    start = prev = None
    for p in pages:
        if start is None:
            start = prev = p
        elif p == prev + 1:
            prev = p
        else:
            parts.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = p
    if start is not None:
        parts.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(parts)


def _azure_value(field: dict | None) -> Any:
    if not field:
        return None
    kind = field.get("type")
    if kind == "currency":
        return (field.get("valueCurrency") or {}).get("amount")
    if kind == "number":
        return field.get("valueNumber")
    if kind == "integer":
        return field.get("valueInteger")
    if kind == "date":
        return field.get("valueDate")
    if kind == "string":
        return field.get("valueString")
    return field.get("content")


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return _clean_cell(value)


AZURE_ITEM_COLUMNS = [
    ("ProductCode", "Product code"),
    ("Description", "Description"),
    ("Quantity", "Quantity"),
    ("Unit", "Unit"),
    ("UnitPrice", "Unit price"),
    ("Amount", "Amount"),
]


def parse_azure_invoice(result: dict) -> tuple[dict[int, list[dict]], dict]:
    """analyzeResult -> ({page: [table]}, document meta)."""
    by_page: dict[int, list[list[str]]] = {}
    conf_by_page: dict[int, list[float | None]] = {}
    meta: dict[str, Any] = {}
    for document in result.get("documents") or []:
        fields = document.get("fields") or {}
        for key, out in (
            ("VendorName", "supplier_name"),
            ("CustomerName", "buyer_or_store_name"),
            ("InvoiceId", "document_number"),
            ("InvoiceDate", "document_date"),
        ):
            value = _azure_value(fields.get(key))
            if value and not meta.get(out):
                meta[out] = _clean_cell(value)
        for key, out in (("InvoiceTotal", "total_amount"), ("SubTotal", "subtotal")):
            value = _azure_value(fields.get(key))
            if isinstance(value, (int, float)):
                meta[out] = (meta.get(out) or 0) + value
        currency = ((fields.get("InvoiceTotal") or {}).get("valueCurrency") or {}).get("currencyCode")
        if currency and not meta.get("currency"):
            meta["currency"] = currency
        for item in (fields.get("Items") or {}).get("valueArray") or []:
            values = item.get("valueObject") or {}
            regions = item.get("boundingRegions") or []
            page = int(regions[0].get("pageNumber", 1)) if regions else 1
            row = [_fmt(_azure_value(values.get(key))) for key, _ in AZURE_ITEM_COLUMNS]
            if not any(row):
                continue
            by_page.setdefault(page, []).append(row)
            conf_by_page.setdefault(page, []).append(item.get("confidence"))
    headers = [label for _, label in AZURE_ITEM_COLUMNS]
    tables = {
        page: [{"headers": headers, "rows": rows, "confidence": conf_by_page.get(page)}]
        for page, rows in by_page.items()
    }
    meta["document_type"] = "invoice"
    return tables, meta


def _azure_analyze(data: bytes, content_type: str, pages: list[int] | None) -> dict:
    endpoint = os.environ["AZURE_DI_ENDPOINT"].rstrip("/")
    key = os.environ["AZURE_DI_KEY"]
    params = {"api-version": os.getenv("AZURE_DI_API_VERSION", "2024-11-30")}
    if pages:
        params["pages"] = page_ranges(pages)
    response = requests.post(
        f"{endpoint}/documentintelligence/documentModels/prebuilt-invoice:analyze",
        params=params,
        headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": content_type},
        data=data,
        timeout=180,
    )
    if response.status_code != 202:
        raise RuntimeError(f"Azure analyze failed ({response.status_code}): {response.text[:300]}")
    operation = response.headers["Operation-Location"]
    deadline = time.time() + 900
    while time.time() < deadline:
        time.sleep(2)
        status = requests.get(operation, headers={"Ocp-Apim-Subscription-Key": key}, timeout=60).json()
        state = status.get("status")
        if state == "succeeded":
            return status.get("analyzeResult") or {}
        if state == "failed":
            raise RuntimeError(f"Azure analyze failed: {str(status.get('error'))[:300]}")
    raise TimeoutError("Azure analyze timed out")


def _mistral_ocr(file_url: str, is_image: bool, pages: list[int]) -> dict[int, list[list[list[str]]]]:
    key = os.environ["MISTRAL_API_KEY"]
    model = os.getenv("MISTRAL_OCR_MODEL", "mistral-ocr-latest")
    document = (
        {"type": "image_url", "image_url": file_url}
        if is_image
        else {"type": "document_url", "document_url": file_url}
    )
    chunks = [[1]] if is_image else [pages[i : i + MISTRAL_PAGES_PER_CALL] for i in range(0, len(pages), MISTRAL_PAGES_PER_CALL)]
    out: dict[int, list[list[list[str]]]] = {}
    for chunk in chunks:
        body: dict[str, Any] = {"model": model, "document": document}
        if not is_image:
            body["pages"] = [p - 1 for p in chunk]
        response = requests.post(
            "https://api.mistral.ai/v1/ocr",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
            timeout=600,
        )
        if response.status_code >= 300:
            raise RuntimeError(f"Mistral OCR failed ({response.status_code}): {response.text[:300]}")
        for page in response.json().get("pages") or []:
            page_no = int(page.get("index", 0)) + 1
            raw = parse_markdown_tables(page.get("markdown") or "") + parse_html_tables(page.get("markdown") or "")
            for table in page.get("tables") or []:
                content = table.get("content") or ""
                raw += parse_html_tables(content) if "<table" in content.lower() else parse_markdown_tables(content)
            out[page_no] = raw
    return out


# --------------------------------------------------------------------------- job


def _download(url: str) -> bytes:
    with requests.get(url, stream=True, timeout=180) as response:
        response.raise_for_status()
        buf = io.BytesIO()
        for chunk in response.iter_content(1024 * 1024):
            buf.write(chunk)
            if buf.tell() > MAX_DOCUMENT_BYTES:
                raise ValueError("Document is larger than 80 MB.")
        return buf.getvalue()


def _update(job_id: str, **changes: Any) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(changes)


def _run(job_id: str, file_url: str, mime_type: str) -> dict:
    import pdfplumber

    data = _download(file_url)
    is_image = mime_type.startswith("image/")
    _update(job_id, data=data)
    provider = ocr_provider()
    pages: dict[int, dict[str, Any]] = {}
    scanned: list[int] = []
    previous_header: list[str] | None = None

    if is_image:
        _update(job_id, pages_total=1, stage="ocr")
        scanned = [1]
        pages[1] = {"page": 1, "source": "none", "tables": [], "text_chars": 0}
    else:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            total = len(pdf.pages)
            if total > MAX_PAGES:
                raise ValueError(f"Document has {total} pages; the limit is {MAX_PAGES}.")
            _update(job_id, pages_total=total, stage="text")
            for index, page in enumerate(pdf.pages, start=1):
                chars = len(page.chars)
                entry: dict[str, Any] = {"page": index, "source": "text", "tables": [], "text_chars": chars}
                if chars >= TEXT_PAGE_MIN_CHARS:
                    tables, previous_header = _tables_from_raw(_text_layer_tables(page), previous_header)
                    entry["tables"] = tables
                else:
                    entry["source"] = "none"
                    scanned.append(index)
                pages[index] = entry
                page.close()
                _update(job_id, pages_done=index)

    meta: dict[str, Any] = {}
    if scanned and provider != "none":
        _update(job_id, stage="ocr", ocr_pages=len(scanned))
        if provider == "azure":
            result = _azure_analyze(data, mime_type, None if is_image else scanned)
            tables_by_page, meta = parse_azure_invoice(result)
            for page_no in scanned:
                pages[page_no]["source"] = "azure"
                pages[page_no]["tables"] = tables_by_page.get(page_no, [])
        else:
            raw_by_page = _mistral_ocr(file_url, is_image, scanned)
            header = None
            for page_no in scanned:
                tables, header = _tables_from_raw(raw_by_page.get(page_no, []), header)
                pages[page_no]["source"] = "mistral"
                pages[page_no]["tables"] = tables

    return {
        "provider": provider,
        "pages_total": len(pages),
        "scanned_pages": len(scanned),
        "document": meta,
        "pages": [pages[p] for p in sorted(pages)],
    }


def _purge_expired() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS
    with _lock:
        for job_id in [k for k, v in _jobs.items() if v.get("created_at", 0) < cutoff]:
            _jobs.pop(job_id, None)


def start_document_job(file_url: str, mime_type: str, filename: str | None = None) -> dict[str, Any]:
    _purge_expired()
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {
            "status": "processing",
            "stage": "download",
            "pages_total": None,
            "pages_done": 0,
            "ocr_pages": 0,
            "result": None,
            "error": None,
            "mime_type": mime_type,
            "filename": filename,
            "data": None,
            "created_at": time.time(),
        }

    def _worker() -> None:
        try:
            result = _run(job_id, file_url, mime_type)
            _update(job_id, status="completed", stage="done", result=result)
        except Exception as exc:
            print(f"Document job {job_id} FAILED: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
            message = str(exc) if isinstance(exc, ValueError) else "Could not read this document."
            _update(job_id, status="failed", error=message)

    threading.Thread(target=_worker, daemon=True).start()
    return {"job_id": job_id, "status": "processing"}


def get_document_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        payload = {
            "job_id": job_id,
            "status": job["status"],
            "stage": job["stage"],
            "pages_total": job["pages_total"],
            "pages_done": job["pages_done"],
            "ocr_pages": job["ocr_pages"],
        }
        if job["status"] == "completed":
            payload["result"] = job["result"]
        if job["status"] == "failed":
            payload["error"] = job["error"]
        return payload


def render_page_jpeg(job_id: str, page_no: int) -> bytes | None:
    """One page as JPEG, for Luna to re-read pages the fast path could not."""
    with _lock:
        job = _jobs.get(job_id)
        data = job.get("data") if job else None
        mime_type = job.get("mime_type") if job else None
    if not data:
        return None
    from PIL import Image

    if mime_type and mime_type.startswith("image/"):
        if page_no != 1:
            return None
        image = Image.open(io.BytesIO(data)).convert("RGB")
    else:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if page_no < 1 or page_no > len(pdf.pages):
                return None
            image = pdf.pages[page_no - 1].to_image(resolution=PAGE_RENDER_DPI).original.convert("RGB")
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=88)
    return out.getvalue()
