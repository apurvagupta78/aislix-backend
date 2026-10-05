from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.auth import (
    assert_fetchable_url,
    auth_status,
    edge_ip,
    enforce_limits,
    limiter,
    remember_job_owner,
    require_job_owner,
    require_scan_access,
    require_user,
)

load_dotenv()

LANDING_SCAN_GLOBAL_DAILY_LIMIT = int(os.getenv("LANDING_SCAN_GLOBAL_DAILY_LIMIT", "150"))
LANDING_SCAN_EDGE_DAILY_LIMIT = int(os.getenv("LANDING_SCAN_EDGE_DAILY_LIMIT", "100"))
MAX_LANDING_BODY_BYTES = 12 * 1024 * 1024
MAX_LANDING_TEXT_CHARS = 60_000
MAX_LANDING_PLANOGRAM_CHARS = 400_000
MAX_SCAN_PHOTOS = 8
MAX_LANDING_REFERENCE_LINES = 200


def _checked_fetch_url(url: str) -> str:
    try:
        assert_fetchable_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return url

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

DEFAULT_ORIGINS = [
    "https://aislix.lovable.app",
    "https://app.aislix.com",
    "https://aislix.com",
    "https://www.aislix.com",
]

cors_origins = os.getenv("CORS_ORIGINS", ",".join(DEFAULT_ORIGINS))
allow_origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]

app = FastAPI(title="Aislix API", version="1.0.0")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    from app.user_errors import MSG_SERVER_ERROR, public_http_detail

    if isinstance(exc, HTTPException):
        detail = public_http_detail(exc.status_code, exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})
    print(f"Unhandled error on {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={"detail": MSG_SERVER_ERROR})


app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    port = os.getenv("PORT", "8080")
    from app.learned_catalog import load_learned
    from app.ocr_reader import active_ocr_engine
    from app.recognizer import active_recognition_mode
    from app.retailklip import ensure_checkpoint, is_available

    learned = load_learned()
    ensure_checkpoint()
    rk = "yes" if is_available() else "no"
    ocr = active_ocr_engine() or "none"
    mode = active_recognition_mode()
    print(
        f"Aislix API starting on 0.0.0.0:{port} "
        f"(recognition={mode}, learned SKUs: {learned}, RetailKLIP: {rk}, OCR: {ocr}, "
        f"OCR requested: {os.getenv('OCR_ENGINE', 'easyocr')})"
    )


@app.get("/")
def home():
    return {
        "message": "Aislix Backend is running",
        "version": "1.0.0",
        "frontend": "https://aislix.com",
    }


@app.get("/health")
def health():
    from app.fnv_qc import is_fnv_qc_metadata
    from app.learned_catalog import count_learned
    from app.make_scan import scan_provider
    from app.recognizer import active_recognition_mode

    return {
        "status": "ok",
        "faiss_ready": (DATA_DIR / "faiss.index").exists() and (DATA_DIR / "catalog.json").exists(),
        "learned_skus": count_learned(),
        "recognition_mode": active_recognition_mode(),
        "recognition_strict": os.getenv("RECOGNITION_STRICT", "true"),
        "recognition_v3": os.getenv("RECOGNITION_V3", "false"),
        **_ocr_status_detail(),
        "retailklip": _retailklip_status(),
        "scan_provider": scan_provider(),
        # Ops marker: true when FNV disposition short-circuit is loaded (commit 88de1e1+).
        "fnv_qc_finalize": is_fnv_qc_metadata({"analysis_mode": "fnv_qc"}),
        "build": "fnv-qc-finalize-v1",
        "auth": auth_status(),
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
def scan_status(scan_id: str, request: Request, user_id: str | None = Depends(require_user)):
    from app.jobs import get_job

    require_scan_access(request, user_id, scan_id)
    job = get_job(scan_id)
    if not job:
        raise HTTPException(status_code=404, detail="Scan job not found.")
    return job


@app.post("/scan")
async def scan(request: Request, user_id: str | None = Depends(require_user)):
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

        scan_id = str(form.get("scan_id") or "").strip()
        if scan_id:
            require_scan_access(request, user_id, scan_id)
        # Legacy sync path when no scan_id (simple uploads).
        if not scan_id:
            try:
                return run_scan_from_bytes(data)
            except Exception as disc:
                from app.user_errors import public_error_from_exception

                raise HTTPException(
                    status_code=422, detail=public_error_from_exception(disc)
                ) from disc

        def _form_text(key: str) -> str | None:
            raw = form.get(key)
            if raw is None:
                return None
            text = str(raw).strip()
            return text or None

        metadata = {
            "store_id": _form_text("store_id"),
            "location": _form_text("location"),
            "shelf_label": _form_text("shelf_label"),
            "category": _form_text("category"),
            "notes": _form_text("notes"),
            "sub_category": _form_text("sub_category"),
            "operating_model": _form_text("operating_model"),
            "analysis_mode": _form_text("analysis_mode"),
            "vision_prompt": _form_text("vision_prompt"),
            "focus_brand": _form_text("focus_brand"),
            "purpose": _form_text("purpose"),
            "expected_products": [],
            "skip_reference_cache": _form_text("skip_reference_cache"),
        }
        from app.fnv_qc import normalize_fnv_qc_metadata

        metadata = normalize_fnv_qc_metadata(metadata)
        mode = str(metadata.get("analysis_mode") or "").strip().lower()
        if mode in {"shelf_only", "no_planogram", "image_only_shelf_analysis"}:
            metadata["planogram_items"] = []
            metadata["planogram_items_full"] = []
            metadata.pop("planogram_version_id", None)
            metadata["expected_products"] = []

        from app.scan_context import build_shelf_label, validate_scan_metadata

        validation_errors = validate_scan_metadata(metadata)
        if validation_errors:
            raise HTTPException(status_code=400, detail="; ".join(validation_errors))
        if not metadata.get("shelf_label"):
            metadata["shelf_label"] = build_shelf_label(
                location=metadata.get("location"),
            ) or None

        existing = get_job(scan_id)
        if existing:
            if existing["status"] == "completed" and existing.get("result"):
                return existing["result"]
            if existing["status"] == "processing":
                return JSONResponse(
                    status_code=202,
                    content={"scan_id": scan_id, "status": "processing"},
                )

        def _run_bytes() -> dict:
            return run_scan_from_bytes(data, scan_id=scan_id, metadata=metadata)

        started = start_job(scan_id, _run_bytes)
        return JSONResponse(status_code=202, content=started)

    if "application/json" in content_type:
        body = await request.json()
        scan_id = body.get("scan_id")
        if not scan_id:
            raise HTTPException(status_code=400, detail="scan_id is required.")
        require_scan_access(request, user_id, str(scan_id))

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
            "category_selections": body.get("category_selections"),
            "sub_categories": body.get("sub_categories"),
            "categories": body.get("categories"),
            "planogram_items": body.get("planogram_items"),
            "planogram_items_full": body.get("planogram_items_full"),
            "audit_package": body.get("audit_package"),
            "planogram_version_id": body.get("planogram_version_id"),
            "primary_brand": body.get("primary_brand"),
            "customer_type": body.get("customer_type"),
            "operating_model": body.get("operating_model"),
            "analysis_mode": body.get("analysis_mode"),
            "vision_prompt": body.get("vision_prompt"),
            "focus_brand": body.get("focus_brand"),
            "purpose": body.get("purpose"),
            "expected_products": body.get("expected_products") or [],
            "skip_reference_cache": body.get("skip_reference_cache"),
            "comparison_basis": body.get("comparison_basis"),
            "reference_items": body.get("reference_items"),
            "reference_document": body.get("reference_document"),
        }
        from app.fnv_qc import normalize_fnv_qc_metadata

        metadata = normalize_fnv_qc_metadata(metadata)
        # shelf_only must never carry planogram rows — they flip comparison mode
        # and bloat the vision prompt until Astra returns unparseable JSON.
        mode = str(metadata.get("analysis_mode") or "").strip().lower()
        if mode in {"shelf_only", "no_planogram", "image_only_shelf_analysis"}:
            metadata["planogram_items"] = []
            metadata["planogram_items_full"] = []
            metadata.pop("planogram_version_id", None)
            metadata["expected_products"] = []

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
            # Failed jobs must be re-runnable (Retry / re-process same scan_id).
            # Fall through so start_job replaces the failed entry.

        image_url = _checked_fetch_url(str(image_urls[0]))
        extra_image_urls = [
            _checked_fetch_url(str(u)) for u in image_urls[1:MAX_SCAN_PHOTOS] if u
        ]
        learned_catalog = body.get("learned_catalog") or []

        def _run() -> dict:
            if learned_catalog:
                from app.learned_catalog import import_learned_catalog

                import_learned_catalog(learned_catalog)
            return run_scan_from_url(
                image_url,
                scan_id=scan_id,
                metadata=metadata,
                extra_image_urls=extra_image_urls,
            )

        started = start_job(scan_id, _run)
        return JSONResponse(status_code=202, content=started)

    raise HTTPException(
        status_code=400,
        detail='Expected multipart file upload or JSON body with "image_urls".',
    )


@app.post("/scan/export-assets")
async def export_assets(request: Request, user_id: str | None = Depends(require_user)):
    """Regenerate PDF, annotated image, and CSV from a shelf image URL (sync)."""
    from app.pipeline import run_scan_from_url

    body = await request.json()
    image_url = body.get("image_url")
    if not image_url:
        raise HTTPException(status_code=400, detail="image_url is required.")
    _checked_fetch_url(str(image_url))
    if body.get("scan_id"):
        require_scan_access(request, user_id, str(body.get("scan_id")))

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
        from app.user_errors import public_error_from_exception

        raise HTTPException(
            status_code=422,
            detail=public_error_from_exception(exc, context="export"),
        ) from exc

    return {
        "pdf_base64": result.get("pdf_base64"),
        "annotated_image_base64": result.get("annotated_image_base64"),
        "original_image_base64": result.get("original_image_base64"),
        "csv_base64": result.get("csv_base64"),
    }


@app.post("/scan/rebuild-pdf", dependencies=[Depends(require_user)])
async def rebuild_pdf(request: Request):
    """Rebuild PDF from stored metrics/inventory + optional human verification (no re-scan)."""
    from app.report_generator import generate_pdf_bytes, build_report_context

    body = await request.json()
    scan_id = str(body.get("scan_id") or "rebuild")
    metrics = body.get("metrics") if isinstance(body.get("metrics"), dict) else {}
    inventory = body.get("inventory") if isinstance(body.get("inventory"), list) else []
    shares = body.get("shares") if isinstance(body.get("shares"), list) else []
    recommendations = body.get("recommendations") if isinstance(body.get("recommendations"), list) else []
    alerts = body.get("alerts") if isinstance(body.get("alerts"), list) else []
    compliance_alerts = (
        body.get("compliance_alerts") if isinstance(body.get("compliance_alerts"), list) else []
    )
    executive_summary = body.get("executive_summary")
    human_verification = body.get("human_verification")
    if isinstance(human_verification, dict):
        metrics = {**metrics, "human_verification": human_verification}

    annotated_jpeg = None
    annotated_b64 = body.get("annotated_image_base64")
    if isinstance(annotated_b64, str) and annotated_b64.strip():
        import base64

        raw = annotated_b64.strip()
        if "," in raw and raw.lower().startswith("data:"):
            raw = raw.split(",", 1)[1]
        try:
            annotated_jpeg = base64.b64decode(raw)
        except Exception:
            annotated_jpeg = None

    report_ctx = build_report_context(
        scan_id=scan_id,
        metrics=metrics,
        store_id=body.get("store_id"),
        location=body.get("location") or body.get("shelf_label"),
        category=body.get("category"),
    )
    try:
        pdf_b64 = generate_pdf_bytes(
            scan_id=scan_id,
            metrics=metrics,
            inventory=inventory,
            shares=shares,
            recommendations=recommendations,
            alerts=alerts,
            compliance_alerts=compliance_alerts,
            executive_summary=executive_summary,
            annotated_jpeg=annotated_jpeg,
            report_context=report_ctx,
        )
    except Exception as exc:
        print(f"PDF rebuild failed for {scan_id}: {exc}")
        raise HTTPException(status_code=500, detail="Could not rebuild the PDF report.") from exc

    return {"pdf_base64": pdf_b64, "build": "human-verification-pdf-v1"}


@app.post("/evidence/photo-metrics")
async def evidence_photo_metrics(request: Request, user_id: str | None = Depends(require_user)):
    """Capture time, fingerprint and quality numbers of an audit evidence photo (signed storage URL)."""
    from starlette.concurrency import run_in_threadpool

    from app.evidence_photo import download_photo, photo_metrics

    if not limiter.allow(f"evidence-photo:{user_id or edge_ip(request) or 'unknown'}", 1200, 3600):
        raise HTTPException(status_code=429, detail="Too many photos checked in the last hour. Try again later.")
    body = await request.json()
    image_url = _checked_fetch_url(str(body.get("image_url") or "").strip())
    if image_url.startswith("data:"):
        raise HTTPException(status_code=400, detail="image_url must be a storage URL.")
    try:
        data = await run_in_threadpool(download_photo, image_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await run_in_threadpool(photo_metrics, data)


@app.post("/documents/read")
async def documents_read(request: Request, user_id: str | None = Depends(require_user)):
    """Start a page-by-page read of a reference document (PDF or photo) from a signed URL."""
    from app.document_reader import start_document_job

    body = await request.json()
    file_url = str(body.get("file_url") or "").strip()
    mime_type = str(body.get("mime_type") or "").strip().lower()
    if not file_url.startswith("https://"):
        raise HTTPException(status_code=400, detail="file_url must be an https URL.")
    _checked_fetch_url(file_url)
    if mime_type not in {"application/pdf", "image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=400, detail="Upload a PDF or a JPG, PNG or WebP image.")
    started = start_document_job(file_url, mime_type, body.get("filename"))
    if isinstance(started, dict):
        remember_job_owner(str(started.get("job_id") or ""), user_id)
    return started


@app.get("/documents/read/{job_id}")
def documents_read_status(job_id: str, user_id: str | None = Depends(require_user)):
    from app.document_reader import get_document_job

    require_job_owner(job_id, user_id)
    job = get_document_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Document job not found.")
    return job


@app.get("/documents/read/{job_id}/page/{page_no}.jpg")
def documents_read_page(job_id: str, page_no: int, user_id: str | None = Depends(require_user)):
    from app.document_reader import render_page_jpeg

    require_job_owner(job_id, user_id)
    image = render_page_jpeg(job_id, page_no)
    if image is None:
        raise HTTPException(status_code=404, detail="Page not found.")
    return Response(content=image, media_type="image/jpeg")


MAX_PLANOGRAM_BODY_BYTES = 2 * 1024 * 1024


async def _capped_json(request: Request, route: str) -> dict:
    """Anonymous planogram helpers: bounded body size and request rate."""
    enforce_limits(request, route, per_ip=120, global_limit=3000, window_seconds=3600)
    if int(request.headers.get("content-length") or 0) > MAX_PLANOGRAM_BODY_BYTES:
        raise HTTPException(status_code=413, detail="File is too large (max 2 MB).")
    raw = await request.body()
    if len(raw) > MAX_PLANOGRAM_BODY_BYTES:
        raise HTTPException(status_code=413, detail="File is too large (max 2 MB).")
    try:
        import json

        body = json.loads(raw or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Expected JSON body.") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object.")
    return body


@app.post("/planogram/parse-csv")
async def planogram_parse_csv(request: Request):
    """Validate planogram CSV; returns preview rows and errors (no DB write)."""
    from app.planogram_csv import parse_csv_text

    content_type = request.headers.get("content-type", "")
    if int(request.headers.get("content-length") or 0) > MAX_PLANOGRAM_BODY_BYTES:
        raise HTTPException(status_code=413, detail="File is too large (max 2 MB).")
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise HTTPException(status_code=400, detail='Missing "file" in multipart body.')
        enforce_limits(request, "planogram_parse", per_ip=120, global_limit=3000, window_seconds=3600)
        raw = await upload.read()
        if len(raw) > MAX_PLANOGRAM_BODY_BYTES:
            raise HTTPException(status_code=413, detail="File is too large (max 2 MB).")
        text = raw.decode("utf-8-sig", errors="replace")
    else:
        body = await _capped_json(request, "planogram_parse")
        text = body.get("csv_text") or body.get("content") or ""
        if not text:
            raise HTTPException(status_code=400, detail="csv_text or file is required.")

    return parse_csv_text(text)


@app.post("/planogram/compare")
async def planogram_compare(request: Request):
    """Compare expected planogram rows vs scan inventory (standalone or post-scan)."""
    from app.planogram_compliance import compare_planogram

    body = await _capped_json(request, "planogram_compare")
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

    body = await _capped_json(request, "planogram_row")
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
        "A-1-Z,Personal Care,Shampoo,Dove,Intense Repair Shampoo,340ml,4,2,6,12,299,6,DOVE-IR-340,1"
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
            "expected_facings or expected_qty",
        ],
        "optional_columns": [
            "variant",
            "min_facings",
            "max_facings",
            "expected_shelf_units",
            "mrp_inr",
            "avg_daily_sales",
            "sku",
            "shelf_position",
        ],
    }


@app.get("/planogram/csv-template/{kind}")
async def planogram_supplement_csv_template(kind: str):
    """Download CSV template for assortment, prices, or promotions."""
    from app.planogram_package_csv import template_csv

    try:
        payload = template_csv(kind)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"kind": kind, **payload}


@app.post("/planogram/parse-package-csv")
async def planogram_parse_package_csv(request: Request):
    """Validate assortment, prices, or promotions CSV."""
    from app.planogram_package_csv import parse_assortment_csv, parse_prices_csv, parse_promotions_csv

    body = await _capped_json(request, "planogram_package")
    kind = str(body.get("kind") or "").strip().lower()
    content = body.get("content") or body.get("csv") or ""
    parsers = {
        "assortment": parse_assortment_csv,
        "prices": parse_prices_csv,
        "promotions": parse_promotions_csv,
    }
    parser = parsers.get(kind)
    if not parser:
        raise HTTPException(status_code=400, detail="kind must be assortment, prices, or promotions")
    return parser(content)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _public_base_url(request: Request) -> str:
    """HTTPS-aware public URL behind Railway / reverse proxies."""
    from app.landing_leads import public_base_url_from_headers

    return public_base_url_from_headers(
        dict(request.headers),
        fallback_scheme=request.url.scheme,
        fallback_host=request.url.netloc,
    )


def _form_field_str(form: dict, key: str) -> str | None:
    val = form.get(key)
    if val is None:
        return None
    if hasattr(val, "read"):
        return None
    text = str(val).strip()
    return text or None


def _payload_field(form: dict, key: str):
    val = form.get(key)
    if val is None:
        return None
    if isinstance(val, (list, dict)):
        return val
    if hasattr(val, "read"):
        return None
    text = str(val).strip()
    if not text:
        return None
    if text.startswith("[") or text.startswith("{"):
        import json

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text


def _merge_astra_payload(metadata: dict, payload: dict) -> dict:
    merged = dict(metadata)
    for key in ("vision_prompt", "analysis_mode", "operating_model", "customer_type"):
        value = _payload_field(payload, key)
        if value:
            merged[key] = value
    for key in ("planogram_items", "expected_products"):
        value = _payload_field(payload, key)
        if isinstance(value, list) and value:
            merged[key] = value
    reference_items = _payload_field(payload, "reference_items")
    if (
        _payload_field(payload, "comparison_basis") == "reference"
        and isinstance(reference_items, list)
        and reference_items
    ):
        merged["comparison_basis"] = "reference"
        merged["reference_items"] = [i for i in reference_items[:MAX_LANDING_REFERENCE_LINES] if isinstance(i, dict)]
        document = _payload_field(payload, "reference_document")
        if isinstance(document, dict):
            merged["reference_document"] = document
    return merged


async def _parse_landing_scan_payload(request: Request) -> dict:
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="JSON body must be an object.")
        return body
    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        return dict(form)
    raise HTTPException(
        status_code=400,
        detail=(
            "Expected multipart/form-data, application/x-www-form-urlencoded, "
            "or application/json with sample_id or file."
        ),
    )


@app.get("/landing/samples")
def landing_samples(request: Request):
    from app.landing_leads import list_samples

    base = _public_base_url(request)
    samples = list_samples()
    for sample in samples:
        sample["preview_url"] = f"{base}/landing/samples/{sample['sample_id']}/image"
    return {"samples": samples}


@app.get("/landing/samples/{sample_id}/image")
def landing_sample_image(sample_id: str):
    from app.landing_leads import resolve_sample_image

    try:
        data, _ = resolve_sample_image(sample_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/landing/session/{session_token}")
def landing_get_session(session_token: str):
    from app.landing_leads import get_session_public

    session = get_session_public(session_token)
    if not session:
        raise HTTPException(status_code=404, detail="Landing session not found.")
    return session


@app.post("/landing/share/persist")
async def landing_share_persist(request: Request):
    """Retired: demo shares are created from server-recorded sessions on aislix.com."""
    raise HTTPException(status_code=410, detail="Share links are created on aislix.com.")


@app.post("/landing/scan")
async def landing_scan(request: Request):
    """Anonymous shelf scan for /retail-intelligence — no signup required."""
    from app.landing_leads import (
        DEFAULT_SAMPLE_ID,
        ENABLED,
        MAX_BYTES,
        create_pending_session,
        hash_ip,
        landing_metadata,
        landing_scan_response,
        merge_landing_vision_metadata,
        parse_utm,
        resolve_sample_image,
        save_scan_failure,
        save_scan_success,
        upload_scan_image,
    )
    from app.detector import load_image_bytes
    from app.pipeline import run_scan_from_image
    from app.reference_scan_cache import sample_id_for_image

    if not ENABLED:
        raise HTTPException(status_code=503, detail="Landing scans are temporarily disabled.")
    if int(request.headers.get("content-length") or 0) > MAX_LANDING_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB).")
    # Visitor IP arrives in X-Forwarded-For from the aislix.com proxy and can be forged by
    # direct callers, so the connecting edge address gets its own daily ceiling.
    if not limiter.allow(f"landing_scan:edge:{edge_ip(request) or 'unknown'}", LANDING_SCAN_EDGE_DAILY_LIMIT, 86400):
        raise HTTPException(
            status_code=429,
            detail="The free demo is busy right now. Sign up free to run your own AI audits.",
        )

    ip_hash = hash_ip(_client_ip(request))
    from app.landing_leads import demo_allowance_response, get_demo_allowance

    allowance = get_demo_allowance(ip_hash)
    if not allowance["allowed"]:
        next_at = allowance.get("next_available_at")
        detail = (
            f"Free demo limit reached ({allowance['limit']} AI audits). "
            f"Your next AI audit will be available 24 hours after your last completed demo audit."
        )
        if next_at:
            detail += f" Next available: {next_at}."
        raise HTTPException(status_code=429, detail=detail)
    if not limiter.allow("landing_scan:global", LANDING_SCAN_GLOBAL_DAILY_LIMIT, 86400):
        raise HTTPException(
            status_code=429,
            detail="The free demo is busy right now. Sign up free to run your own AI audits.",
        )

    payload = await _parse_landing_scan_payload(request)
    for key, cap in (
        ("vision_prompt", MAX_LANDING_TEXT_CHARS),
        ("planogram_items", MAX_LANDING_PLANOGRAM_CHARS),
        ("reference_items", MAX_LANDING_PLANOGRAM_CHARS),
    ):
        value = payload.get(key)
        if value is not None and not hasattr(value, "read"):
            import json

            size = len(value) if isinstance(value, str) else len(json.dumps(value))
            if size > cap:
                raise HTTPException(status_code=413, detail="Audit setup is too large for the free demo.")
    utm = parse_utm(payload)
    session_token = (
        _form_field_str(payload, "landing_session_id")
        or _form_field_str(payload, "session_token")
    )
    sample_id = _form_field_str(payload, "sample_id")
    category = _form_field_str(payload, "category")
    location = _form_field_str(payload, "location")
    shelf_label = _form_field_str(payload, "shelf_label")
    sub_category = _form_field_str(payload, "sub_category")
    sub_category_label = _form_field_str(payload, "sub_category_label")
    referrer = request.headers.get("referer") or request.headers.get("referrer")
    user_agent = request.headers.get("user-agent")

    image_bytes: bytes | None = None
    sample_defaults: dict[str, str] = {}
    is_user_upload = False
    upload = payload.get("file")
    if sample_id:
        try:
            image_bytes, sample_defaults = resolve_sample_image(sample_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        category = category or sample_defaults.get("category")
        location = location or sample_defaults.get("location")
        shelf_label = shelf_label or sample_defaults.get("shelf_label")
    elif upload is not None and hasattr(upload, "read"):
        is_user_upload = True
        image_bytes = await upload.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="Empty file upload.")
        if len(image_bytes) > MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Image too large (max {MAX_BYTES // (1024 * 1024)} MB).",
            )
        from app.landing_leads import validate_landing_upload_context

        try:
            validate_landing_upload_context(category=category, sub_category=sub_category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        sample_id = DEFAULT_SAMPLE_ID
        try:
            image_bytes, sample_defaults = resolve_sample_image(sample_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        category = category or sample_defaults.get("category")
        location = location or sample_defaults.get("location")
        shelf_label = shelf_label or sample_defaults.get("shelf_label")

    token = create_pending_session(
        session_token=session_token,
        ip_hash=ip_hash,
        utm=utm,
        referrer=referrer,
        user_agent=user_agent,
        sample_id=sample_id,
    )
    from app.landing_leads import merge_landing_sample_defaults

    image = load_image_bytes(image_bytes)
    detected_sample_id = sample_id_for_image(image)
    effective_sample_id, merged_defaults = merge_landing_sample_defaults(
        sample_id=sample_id,
        detected_sample_id=detected_sample_id,
        explicit_defaults=sample_defaults or None,
        user_upload=is_user_upload,
    )
    metadata = landing_metadata(
        category,
        location,
        shelf_label,
        sample_id=effective_sample_id,
        sample_defaults=merged_defaults or None,
        sub_category=sub_category,
        sub_category_label=sub_category_label,
        detected_sample_id=detected_sample_id,
        user_upload=is_user_upload,
    )
    metadata = merge_landing_vision_metadata(metadata, payload)
    metadata = _merge_astra_payload(metadata, payload)

    try:
        result = run_scan_from_image(image, metadata=metadata)
    except Exception as exc:
        from app.user_errors import public_error_from_exception

        public_error = public_error_from_exception(exc)
        print(f"Landing scan failed ({token}): {exc}")
        save_scan_failure(token, public_error)
        raise HTTPException(status_code=422, detail=public_error) from exc

    scan_id = result.get("scan_id") or "landing"
    storage_path = upload_scan_image(token, scan_id, image_bytes)
    save_scan_success(
        token,
        scan_id=scan_id,
        sample_id=effective_sample_id,
        image_storage_path=storage_path,
        category=category or merged_defaults.get("category"),
        full_result=result,
    )

    response = landing_scan_response(result, token, sample_id=effective_sample_id)
    response.update(demo_allowance_response(ip_hash))
    return response


@app.post("/landing/email-report")
async def landing_email_report(request: Request):
    """Email a completed demo audit report to a recipient."""
    from app.landing_leads import get_session_public
    from app.landing_report_email import send_demo_audit_report_email

    enforce_limits(request, "email_report", per_ip=5, global_limit=60, window_seconds=3600)
    body = await request.json()
    session_token = (body.get("landing_session_id") or body.get("session_token") or "").strip()
    recipient = (body.get("recipient") or body.get("email") or "").strip().lower()
    message = (body.get("message") or "").strip() or None
    if not session_token:
        raise HTTPException(status_code=400, detail="Missing demo session.")
    if not recipient or "@" not in recipient:
        raise HTTPException(status_code=400, detail="Valid recipient email is required.")

    session = get_session_public(session_token)
    if not session or session.get("status") != "completed":
        raise HTTPException(status_code=404, detail="Demo audit not found or not completed.")

    pdf_bytes = None
    try:
        from app.report_generator import generate_pdf_bytes

        pdf_bytes = generate_pdf_bytes(session)
    except Exception as exc:
        print(f"demo email PDF skipped: {exc}")

    ok, err = send_demo_audit_report_email(
        recipient=recipient,
        session_token=session_token,
        store_name=session.get("shelf_label") or session.get("category"),
        audit_date=session.get("scanned_at"),
        message=message,
        pdf_bytes=pdf_bytes,
    )
    if not ok:
        raise HTTPException(status_code=502, detail=err or "Could not send email.")
    return {"ok": True, "sent": 1}


@app.get("/landing/demo-allowance")
async def landing_demo_allowance(request: Request):
    """Authoritative free demo AI audit allowance for the caller IP."""
    from app.landing_leads import demo_allowance_response, hash_ip

    ip_hash = hash_ip(_client_ip(request))
    return demo_allowance_response(ip_hash)


@app.post("/landing/lead")
async def landing_lead(request: Request):
    """Capture email/details after demo scan and send onboarding email."""
    from app.landing_email import send_landing_onboarding_email
    from app.landing_leads import capture_lead, ensure_session, hash_ip, mark_onboarding_email_sent

    enforce_limits(request, "lead", per_ip=5, global_limit=120, window_seconds=3600)
    body = await request.json()
    session_token = (body.get("landing_session_id") or body.get("session_token") or "").strip() or None
    email = (body.get("email") or "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Valid email is required.")

    utm = {
        "utm_source": body.get("utm_source"),
        "utm_medium": body.get("utm_medium"),
        "utm_campaign": body.get("utm_campaign"),
        "utm_content": body.get("utm_content"),
        "utm_term": body.get("utm_term"),
    }
    ip_hash = hash_ip(_client_ip(request))
    token = ensure_session(session_token, ip_hash=ip_hash, utm=utm)

    row = capture_lead(
        token,
        email=email,
        name=body.get("name"),
        company=body.get("company"),
        phone=body.get("phone"),
        role=body.get("role"),
        ip_hash=ip_hash,
        utm=utm,
    )

    email_sent, email_error, signup_url = send_landing_onboarding_email(
        email=email,
        name=(body.get("name") or "").strip() or None,
        landing_session_id=token,
    )
    if email_sent:
        mark_onboarding_email_sent(token)

    return {
        "ok": True,
        "landing_session_id": token,
        "persisted": bool(row),
        "email_sent": email_sent,
        "signup_url": signup_url,
        "message": "Check your email to continue your Aislix onboarding."
        if email_sent
        else "Details saved. Use the button below to create your free account.",
        "email_error": email_error if not email_sent else None,
    }


@app.post("/landing/convert")
async def landing_convert(request: Request, verified_user_id: str | None = Depends(require_user)):
    """Link a landing demo session to a user after signup."""
    from app.landing_leads import get_session_public, mark_converted

    body = await request.json()
    session_token = (body.get("landing_session_id") or body.get("session_token") or "").strip()
    user_id = verified_user_id
    if not user_id:
        raise HTTPException(status_code=401, detail="Sign in to Aislix to use this feature.")
    if not session_token:
        raise HTTPException(status_code=400, detail="landing_session_id is required.")

    existing = get_session_public(session_token)
    if not existing:
        raise HTTPException(status_code=404, detail="Landing session not found.")

    row = mark_converted(session_token, user_id)
    return {
        "ok": True,
        "landing_session_id": session_token,
        "converted_user_id": user_id,
        "persisted": bool(row),
    }
