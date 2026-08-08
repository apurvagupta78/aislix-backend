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
- `FAISS_SIMILARITY_THRESHOLD=0.85` (optional)
- `OPENAI_VISION_MODEL=gpt-4o-mini` (optional)

## Endpoints

- `GET /health`
- `POST /scan` — multipart file **or** JSON `{ "image_urls": ["..."], "scan_id": "..." }`
