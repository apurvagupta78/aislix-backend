from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.pipeline import run_scan_from_bytes, run_scan_from_url

load_dotenv()

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


@app.get("/")
def home():
    return {"message": "Aislix Backend is running", "version": "1.0.0"}


@app.get("/health")
def health():
    from app.faiss_matcher import is_ready

    return {
        "status": "ok",
        "faiss_ready": is_ready(),
    }


@app.post("/scan")
async def scan(request: Request):
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
        try:
            return run_scan_from_url(image_urls[0], scan_id=scan_id, metadata=metadata)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    raise HTTPException(
        status_code=400,
        detail='Expected multipart file upload or JSON body with "image_urls".',
    )
