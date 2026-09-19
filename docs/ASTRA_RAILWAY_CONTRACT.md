# Astra / Railway vision contract

Frontend sends shelf photos and structured context to Railway FastAPI. **OpenAI credentials stay on Railway only.**

## Environment variables

| Variable | Where | Purpose |
|---|---|---|
| `AISLIX_AI_API_URL` | Frontend host (Vercel/Lovable) | Railway FastAPI base URL |
| `AISLIX_AI_API_KEY` | Frontend host | Auth header to Railway (`Authorization: Bearer …`, `x-api-key`) |
| `OPENAI_API_KEY` | **Railway only** | Astra GPT vision calls |
| `SCAN_PROVIDER=openai` | Railway | Use direct OpenAI vision (required for Astra prompts) |

## Request (POST `/scan` or `/landing/scan`)

```json
{
  "scan_id": "uuid",
  "image_urls": ["signed-url"],
  "customer_type": "supermarket",
  "operating_model": "supermarket",
  "analysis_mode": "planogram_comparison | expected_products | shelf_only",
  "vision_prompt": "full Astra prompt text",
  "planogram_items": [],
  "expected_products": [],
  "category": "Personal Care",
  "sub_category": "toothpaste",
  "audit_package": {}
}
```

### Mode selection

| Condition | `analysis_mode` | List sent |
|---|---|---|
| Planogram rows present | `planogram_comparison` | `planogram_items` (14 CSV fields) |
| No planogram, expected products added | `expected_products` | `expected_products` (8 fields) |
| No planogram, no products | `shelf_only` | neither list |

### Expected product fields

`location`, `category`, `sub_category`, `brand`, `product_name`, `variant`, `expected_facings`, `expected_shelf_units`

## Response

### Planogram comparison

Key: `astra_planogram_analysis`

### Expected products (no planogram)

Key: `astra_expected_products_analysis`

### Shelf-only fallback

Return legacy `inventory[]` + metrics. No comparison table.

## Backend files

- Astra extraction: `app/astra_vision.py`
- OpenAI vision provider: `app/openai_vision_scan.py`
- Scan endpoint metadata: `main.py` (`POST /scan`, `POST /landing/scan`)
