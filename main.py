from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

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
    from app.learned_catalog import count_learned
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
            "category_selections": body.get("category_selections"),
            "sub_categories": body.get("sub_categories"),
            "categories": body.get("categories"),
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
        "original_image_base64": result.get("original_image_base64"),
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


@app.post("/landing/scan")
async def landing_scan(request: Request):
    """Anonymous shelf scan for /retail-intelligence — no signup required."""
    from app.landing_leads import (
        DEFAULT_SAMPLE_ID,
        ENABLED,
        MAX_BYTES,
        check_rate_limit,
        create_pending_session,
        hash_ip,
        landing_metadata,
        landing_scan_response,
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

    ip_hash = hash_ip(_client_ip(request))
    allowed, used, limit = check_rate_limit(ip_hash)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Daily demo scan limit reached ({limit} per day). Sign up for full access.",
        )

    payload = await _parse_landing_scan_payload(request)
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
        image_bytes = await upload.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="Empty file upload.")
        if len(image_bytes) > MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Image too large (max {MAX_BYTES // (1024 * 1024)} MB).",
            )
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
    )

    try:
        result = run_scan_from_image(image, metadata=metadata)
    except Exception as exc:
        save_scan_failure(token, str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

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
    response["scans_used_today"] = used
    response["scans_daily_limit"] = limit
    return response


@app.post("/landing/lead")
async def landing_lead(request: Request):
    """Capture email/details after demo scan and send onboarding email."""
    from app.landing_email import send_landing_onboarding_email
    from app.landing_leads import capture_lead, ensure_session, hash_ip, mark_onboarding_email_sent

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
async def landing_convert(request: Request):
    """Link a landing demo session to a user after signup."""
    from app.landing_leads import get_session_public, mark_converted

    body = await request.json()
    session_token = (body.get("landing_session_id") or body.get("session_token") or "").strip()
    user_id = (body.get("user_id") or "").strip()
    if not session_token or not user_id:
        raise HTTPException(status_code=400, detail="landing_session_id and user_id are required.")

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
