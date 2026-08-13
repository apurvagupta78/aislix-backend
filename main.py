from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

DEFAULT_ORIGINS = [
    "https://aislix.lovable.app",
    "https://id-preview--449a1800-6064-43d4-9afe-f713a920d0d4.lovable.app",
    "https://app.aislix.com",
    "https://aislix.com",
    "https://www.aislix.com",
    "http://localhost:5173",
    "http://localhost:3000",
]

cors_origins = os.getenv("CORS_ORIGINS", ",".join(DEFAULT_ORIGINS))
allow_origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]

app = FastAPI(title="Aislix API", version="1.0.0")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    print(f"Unhandled error on {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"detail": str(exc)[:500]})


app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    port = os.getenv("PORT", "8080")
    from app.learned_catalog import load_learned
    from app.ocr_reader import active_ocr_engine
    from app.retailklip import ensure_checkpoint, is_available

    learned = load_learned()
    ensure_checkpoint()
    rk = "yes" if is_available() else "no"
    ocr = active_ocr_engine() or "none"
    print(f"Aislix API starting on 0.0.0.0:{port} (learned SKUs: {learned}, RetailKLIP: {rk}, OCR: {ocr}, OCR requested: {os.getenv('OCR_ENGINE', 'easyocr')})")


@app.get("/")
def home():
    return {
        "message": "Aislix Backend is running",
        "version": "1.0.0",
        "frontend": "https://aislix.com",
    }


@app.get("/health")
def health():
    from app.learned_catalog import count_learned

    return {
        "status": "ok",
        "faiss_ready": (DATA_DIR / "faiss.index").exists() and (DATA_DIR / "catalog.json").exists(),
        "learned_skus": count_learned(),
        **_ocr_status_detail(),
        "retailklip": _retailklip_status(),
    }


def _retailklip_status() -> bool:
    from app.retailklip import _is_valid_checkpoint, checkpoint_path, ensure_checkpoint

    path = ensure_checkpoint()
    return _is_valid_checkpoint(path)


def _ocr_engine_status() -> str:
    from app.ocr_reader import OCR_ENABLED, ocr_engine_status

    if not OCR_ENABLED:
        return "disabled"
    return ocr_engine_status()["ocr_engine"]


def _ocr_status_detail() -> dict:
    from app.ocr_reader import OCR_ENABLED, ocr_engine_status

    if not OCR_ENABLED:
        return {"ocr_engine": "disabled", "ocr_engine_requested": "disabled", "ocr_fallback_reason": None}
    return ocr_engine_status()


@app.get("/catalog/learned")
def learned_catalog_stats():
    from app.learned_catalog import count_learned, load_learned

    load_learned()
    return {"learned_skus": count_learned()}


@app.get("/categories")
def list_categories():
    from app.scan_context import categories_for_api

    return {"categories": categories_for_api()}


@app.get("/scan/{scan_id}")
def scan_status(scan_id: str):
    from app.jobs import get_job

    job = get_job(scan_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found.")
    return job


@app.post("/scan")
async def scan(request: Request):
    from app.jobs import get_job, start_job
    from app.pipeline import run_scan_from_bytes, run_scan_from_url

    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise HTTPException(status_code=400, detail='Missing "file" in multipart body.')
        data = await upload.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty file upload.")
        try:
            return run_scan_from_bytes(data)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    if "application/json" in content_type:
        body = await request.json()
        scan_id = body.get("scan_id")
        if not scan_id:
            raise HTTPException(status_code=400, detail="scan_id is required.")

        metadata = {
            "store_id": body.get("store_id"),
            "location": body.get("location"),
            "shelf_label": body.get("shelf_label"),
            "category": body.get("category"),
            "notes": body.get("notes"),
            "sub_category": body.get("sub_category"),
            "sub_category_label": body.get("sub_category_label"),
            "sub_category_custom": body.get("sub_category_custom"),
            # legacy fields — still accepted if sent
            "aisle": body.get("aisle"),
            "rack": body.get("rack"),
            "bin": body.get("bin"),
            "beverage_type": body.get("beverage_type"),
            "product_type": body.get("product_type"),
            "assignment_id": body.get("assignment_id"),
            "assignment_scope_type": body.get("assignment_scope_type"),
            "assignment_scope_values": body.get("assignment_scope_values"),
            "planogram_items": body.get("planogram_items"),
            "planogram_items_full": body.get("planogram_items_full"),
        }

        from app.scan_context import build_shelf_label, validate_scan_metadata

        validation_errors = validate_scan_metadata(metadata)
        if validation_errors:
            raise HTTPException(status_code=400, detail="; ".join(validation_errors))

        if not metadata.get("shelf_label"):
            metadata["shelf_label"] = build_shelf_label(
                location=metadata.get("location"),
                aisle=metadata.get("aisle"),
                rack=metadata.get("rack"),
                bin_label=metadata.get("bin"),
            ) or None

        image_urls = body.get("image_urls") or []
        if not image_urls and body.get("images"):
            image_urls = [item.get("url") for item in body["images"] if item.get("url")]
        if not image_urls:
            raise HTTPException(status_code=400, detail="No image_urls provided.")

        existing = get_job(scan_id)
        if existing:
            if existing["status"] == "completed" and existing.get("result"):
                return existing["result"]
            if existing["status"] == "processing":
                return JSONResponse(
                    status_code=202,
                    content={"scan_id": scan_id, "status": "processing"},
                )
            if existing["status"] == "failed":
                error = existing.get("error") or "Scan failed."
                raise HTTPException(status_code=422, detail=error)

        image_url = image_urls[0]
        learned_catalog = body.get("learned_catalog") or []

        def _run() -> dict:
            if learned_catalog:
                from app.learned_catalog import import_learned_catalog

                import_learned_catalog(learned_catalog)
            return run_scan_from_url(image_url, scan_id=scan_id, metadata=metadata)

        started = start_job(scan_id, _run)
        return JSONResponse(status_code=202, content=started)

    raise HTTPException(
        status_code=400,
        detail='Expected multipart file upload or JSON body with "image_urls".',
    )


@app.post("/scan/export-assets")
async def export_assets(request: Request):
    """Regenerate PDF, annotated image, and CSV from a shelf image URL (sync)."""
    from app.pipeline import run_scan_from_url

    body = await request.json()
    image_url = body.get("image_url")
    if not image_url:
        raise HTTPException(status_code=400, detail="image_url is required.")

    metadata = {
        "store_id": body.get("store_id"),
        "location": body.get("location"),
        "shelf_label": body.get("shelf_label"),
        "category": body.get("category"),
    }
    scan_id = body.get("scan_id") or "export"
    try:
        result = run_scan_from_url(image_url, scan_id=scan_id, metadata=metadata)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "pdf_base64": result.get("pdf_base64"),
        "annotated_image_base64": result.get("annotated_image_base64"),
        "csv_base64": result.get("csv_base64"),
    }


@app.post("/planogram/parse-csv")
async def planogram_parse_csv(request: Request):
    """Validate planogram CSV; returns preview rows and errors (no DB write)."""
    from app.planogram_csv import parse_csv_text

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise HTTPException(status_code=400, detail='Missing "file" in multipart body.')
        text = (await upload.read()).decode("utf-8-sig", errors="replace")
    else:
        body = await request.json()
        text = body.get("csv_text") or body.get("content") or ""
        if not text:
            raise HTTPException(status_code=400, detail="csv_text or file is required.")

    return parse_csv_text(text)


@app.post("/planogram/compare")
async def planogram_compare(request: Request):
    """Compare expected planogram rows vs scan inventory (standalone or post-scan)."""
    from app.planogram_compliance import compare_planogram

    body = await request.json()
    planogram_items = body.get("planogram_items") or []
    inventory = body.get("inventory") or []
    if not planogram_items:
        raise HTTPException(status_code=400, detail="planogram_items is required.")
    if not inventory:
        raise HTTPException(status_code=400, detail="inventory is required.")

    result = compare_planogram(
        planogram_items=planogram_items,
        inventory=inventory,
        scan_context=body.get("scan_context") or {},
        scope_type=body.get("scope_type"),
        scope_values=body.get("scope_values") or {},
        full_store_items=body.get("planogram_items_full") or planogram_items,
    )
    return {"planogram_compliance": result}


@app.post("/planogram/normalize-row")
async def planogram_normalize_row(request: Request):
    """Validate a single manual planogram row (Store Master form)."""
    from app.planogram_csv import normalize_planogram_row

    body = await request.json()
    row, errors = normalize_planogram_row(body)
    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))
    return {"row": row}


@app.get("/planogram/csv-template")
async def planogram_csv_template():
    """Downloadable planogram CSV header + example row."""
    from app.planogram_csv import csv_template_header

    header = csv_template_header()
    example = (
        "A-1-Z,Personal Care,Shampoo,Dove,Intense Repair Shampoo,340ml,1,,1"
    )
    return {
        "header": header,
        "example_row": example,
        "csv_text": f"{header}\n{example}\n",
        "required_columns": [
            "location",
            "category",
            "sub_category",
            "brand",
            "product_name",
            "expected_qty",
        ],
        "optional_columns": ["variant", "sku", "shelf_position"],
    }
