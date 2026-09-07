# Aislix Backend

FastAPI shelf-audit API: YOLO detection → FAISS catalog match → GPT Vision fallback.

## Production

| Service | URL |
|---------|-----|
| **Frontend (live)** | https://aislix.com |
| **API (Railway)** | https://aislix-backend-production.up.railway.app |
| **Health check** | `GET /health` |

Railway `CORS_ORIGINS` must include `https://aislix.com`, `https://www.aislix.com`, and `https://app.aislix.com` (plus Lovable preview URLs for staging).

Lovable secret `AISLIX_AI_API_URL` = Railway API URL above (no trailing slash).

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
- `CORS_ORIGINS=https://aislix.lovable.app,https://id-preview--449a1800-6064-43d4-9afe-f713a920d0d4.lovable.app,https://app.aislix.com,https://aislix.com,https://www.aislix.com`
- `FAISS_SIMILARITY_THRESHOLD=0.92` (default in v2 — was 0.85)
- `GPT_MAX_FALLBACKS=80` (smart cap in v2 — was 12)
- `RECOGNITION_V2=true` (OCR-first pipeline; set `false` to revert to v1)
- `OCR_ENABLED=true` / `OCR_LANGUAGES=en`
- `OCR_ENGINE=paddle` (default on Railway Docker; falls back to EasyOCR if Paddle fails to load)
- `OCR_MIN_CONFIDENCE=0.6`
- `LEARN_MIN_CONFIDENCE=0.7` (only OCR/GPT labels above this are learned)
- `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` (optional — for Supabase-backed learned SKU sync; Lovable can persist without these)
- `LEARNED_CATALOG_BUCKET=catalog-data` (optional — Supabase storage bucket name)
- `DETECTION_MODE=standard` (set to `sahi` for slicing-aided tiled YOLO — see `data/benchmark/README.md`)
- `SAHI_TILE_SIZE=640` / `SAHI_OVERLAP_RATIO=0.25` (optional SAHI tuning)

### Vision scan providers (optional)

Replace the local YOLO/OCR pipeline with OpenAI vision directly (**recommended**) or a Make.com webhook:

#### Direct OpenAI (recommended)

- `SCAN_PROVIDER=openai` — call OpenAI from the backend for all scans (`POST /scan`, `POST /landing/scan`, `POST /scan/export-assets`)
- `OPENAI_API_KEY` — required
- `OPENAI_VISION_MODEL=gpt-6-astra` — shelf audit model (A/B tested vs gpt-5.6-sol)
- `OPENAI_VISION_REASONING_EFFORT=medium` — balance speed vs quality on large shelves
- `OPENAI_VISION_MAX_TOKENS=8192` — max output tokens (reasoning models need headroom for JSON)
- `OPENAI_VISION_TIMEOUT_SECONDS=300` — request timeout (complex multi-row shelves may need 3–5 min)
- `OPENAI_VISION_IMAGE_DETAIL=auto` — use `high` only for photos wider/taller than 1024px
- `OPENAI_VISION_MAX_IMAGE_PX=2048` — downscale large uploads before the API call

Uses the same shelf audit prompt as Make (`docs/MAKE_OPENAI_PROMPT.md`) and the same response parser/post-processing as the Make provider.

#### Make.com (legacy)

- `SCAN_PROVIDER=make` — use Make.com for all scans
- `MAKE_SCAN_WEBHOOK_URL` — Make custom webhook URL (required when `SCAN_PROVIDER=make`)
- `MAKE_WEBHOOK_SECRET` — optional shared secret sent as `X-Aislix-Secret`
- `MAKE_SCAN_TIMEOUT_SECONDS=90` — webhook timeout
- `MAKE_FALLBACK_LOCAL=false` — set `true` to retry the local pipeline if Make fails
- `MAKE_UPLOAD_MODE=multipart` — send shelf photo as `image` file (matches Make Custom Webhook); set `json` for base64 payload
- `MAKE_IMAGE_FIELD=image` — multipart file field name (default matches your Shelf Sense AI scenario)

**Request payload** — default multipart (matches Make `image` collection):

- File field `image` — JPEG shelf photo (`name`, `mime`, `data`)
- Form fields: `scan_id`, `category`, `sub_category`, `shelf_label`, `metadata` (JSON when planogram present)

Alternative JSON mode (`MAKE_UPLOAD_MODE=json`):

```json
{
  "scan_id": "abc123",
  "image_base64": "<jpeg>",
  "image_mime": "image/jpeg",
  "image_url": "https://optional-signed-url",
  "metadata": { "category": "Personal Care", "planogram_items": [] }
}
```

**Response** — either full Aislix scan JSON (`inventory` + `metrics` + `executive_summary`), partial inventory/facings, or **Shelf Sense AI** OpenAI output:

```json
{
  "products": [
    {
      "brand": "Crax",
      "product": "Rings",
      "variant": "",
      "qty": 4,
      "confidence": 0.99,
      "shelf_position": "Top Left Front"
    }
  ]
}
```

The webhook may return this as a JSON string (OpenAI `Message.Content`); the backend maps `product` → `product_name`, `qty` → `quantity`/`facings`, and preserves `shelf_position` per row.

Partial responses are normalized by the backend (metrics, PDF, CSV, planogram compare).

**Dashboard compatibility:** Make replaces only AI recognition. The backend still returns the full Aislix scan payload: `inventory`, `products`, `metrics`, `planogram_compliance`, `executive_summary`, `pdf_base64`, `csv_base64`, `original_image_base64`, and `annotated_image_base64`. Without bounding boxes from Make, the annotated image is the clean shelf photo (same as shelfsense1.lovable.app). Planogram compliance still runs when `planogram_items` are sent in scan metadata.

### RetailKLIP on Railway (bundled in Docker)

The fine-tuned checkpoint `models/retailklip_vitb32.pt` (~335 MB) is stored in **Git LFS**. The Dockerfile uses a multi-stage build that `git clone`s the repo and runs `git lfs pull` (Railway’s Docker context does not include `.git`, so a plain `COPY` only gets the pointer stub).

1. Push to the branch Railway deploys from.
2. Railway builds `Dockerfile` — the `lfs-fetch` stage downloads the real checkpoint.
3. Verify: `GET /health` → `"retailklip": true`

If the build fails on `git clone` (private repo), add a Railway build arg `GITHUB_TOKEN` with repo read access.

Set `USE_RETAILKLIP=false` to revert to base OpenCLIP embeddings.

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

Upload to Supabase storage (optional fallback if not using Docker bundle):

```bash
python scripts/upload_retailklip.py
```

Set `USE_RETAILKLIP=false` to revert to base OpenCLIP embeddings.

## Endpoints

- `GET /health`
- `GET /categories` — includes `subcategories[]` per aisle (with Others + custom text)
- `GET /catalog/learned`
- `POST /scan` — multipart file **or** JSON `{ "image_urls", "scan_id", "category", "sub_category", ... }`
- `GET /scan/{scan_id}` — poll async scan status
