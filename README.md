# Aislix Backend

FastAPI shelf-audit API: YOLO detection → FAISS catalog match → GPT Vision fallback.

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Build the product catalog index (once):

```bash
python scripts/build_faiss_index.py --dataset "D:\combinedDataset.v3-dataset_master_file.yolov8"
```

Run the API:

```bash
uvicorn main:app --reload --port 8000
```

## Railway env vars

- `OPENAI_API_KEY`
- `CORS_ORIGINS=https://aislix.lovable.app,https://id-preview--449a1800-6064-43d4-9afe-f713a920d0d4.lovable.app`
- `FAISS_SIMILARITY_THRESHOLD=0.92` (default in v2 — was 0.85)
- `GPT_MAX_FALLBACKS=80` (smart cap in v2 — was 12)
- `RECOGNITION_V2=true` (OCR-first pipeline; set `false` to revert to v1)
- `OCR_ENABLED=true` / `OCR_LANGUAGES=en`
- `OCR_ENGINE=paddle` (default; falls back to `easyocr` if PaddleOCR unavailable)
- `OCR_MIN_CONFIDENCE=0.6`
- `LEARN_MIN_CONFIDENCE=0.7` (only OCR/GPT labels above this are learned)
- `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` (required for persistent learned SKU catalog)
- `LEARNED_CATALOG_BUCKET=catalog-data` (optional — Supabase storage bucket name)

## Learned SKU catalog (auto-learning)

When GPT identifies a product not in the base FAISS catalog, the backend:

1. Saves a CLIP embedding + brand/product/variant to `learned_skus` (Supabase)
2. Adds it to an in-memory **learned FAISS index**
3. Reuses it on future scans via FAISS (`recognition_source: learned`) — **no GPT call**

Check status: `GET /health` → `learned_skus` count  
List count: `GET /catalog/learned`

Apply the Supabase migration in `supabase/migrations/20260808100000_learned_skus.sql` via Lovable Cloud SQL.

To merge learned SKUs into the base catalog offline:

```bash
python scripts/merge_learned_into_base.py
```

### RetailKLIP fine-tuning (Phase 3)

Fine-tune OpenCLIP ViT-B-32 with ArcFace on your YOLO crop dataset:

```bash
python scripts/train_retailklip.py --dataset "D:\combinedDataset.v3-dataset_master_file.yolov8" --epochs 4
python scripts/build_faiss_index.py
```

Set `USE_RETAILKLIP=false` to revert to base OpenCLIP embeddings.

## Endpoints

- `GET /health`
- `GET /catalog/learned`
- `POST /scan` — multipart file **or** JSON `{ "image_urls": ["..."], "scan_id": "..." }`
- `GET /scan/{scan_id}` — poll async scan status
