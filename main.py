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
    "http://localhost:5173",
    "http://localhost:3000",
]

cors_origins = os.getenv("CORS_ORIGINS", ",".join(DEFAULT_ORIGINS))
allow_origins = [origin.strip() for origin in cors_origins.split(",") if origin.strip()]

app = FastAPI(title="Aislix API", version="1.0.0")

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

    learned = load_learned()
    print(f"Aislix API starting on 0.0.0.0:{port} (learned SKUs: {learned})")


@app.get("/")
def home():
    return {"message": "Aislix Backend is running", "version": "1.0.0"}


@app.get("/health")
def health():
    from app.learned_catalog import count_learned

    return {
        "status": "ok",
        "faiss_ready": (DATA_DIR / "faiss.index").exists() and (DATA_DIR / "catalog.json").exists(),
        "learned_skus": count_learned(),
    }


@app.get("/catalog/learned")
def learned_catalog_stats():
    from app.learned_catalog import count_learned, load_learned

    load_learned()
    return {"learned_skus": count_learned()}


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
            "shelf_label": body.get("shelf_label"),
            "category": body.get("category"),
            "notes": body.get("notes"),
        }
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

        def _run() -> dict:
            return run_scan_from_url(image_url, scan_id=scan_id, metadata=metadata)

        started = start_job(scan_id, _run)
        return JSONResponse(status_code=202, content=started)

    raise HTTPException(
        status_code=400,
        detail='Expected multipart file upload or JSON body with "image_urls".',
    )
