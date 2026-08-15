# Lovable: Accuracy correction UI (cross-category)

Add a lightweight **"Improve AI"** workflow on scan results so ops can correct wrong SKUs and feed the backend benchmark loop.

## Backend already provides

From `POST /scan` → `result.metrics`:
- `ocr_empty_facings`
- `ocr_low_confidence_facings`
- `ocr_avg_confidence`
- `recognition_ocr`, `recognition_faiss`, `recognition_gpt`, `recognition_unknown` counts

Optional debug export (internal tooling): pass `export_facings: true` in scan metadata to get `facings_debug[]` with:
- `x1,y1,x2,y2`, `brand`, `product_name`, `sku`
- `pack_text`, `ocr_confidence`, `recognition_source`, `confidence`

## UI requirements

### 1. Scan results — "Needs review" section

Show when **any** of:
- `ocr_low_confidence_facings > 0`
- `recognition_unknown > 0`
- User clicks "Flag for review"

List facings (from stored scan products or future `scan_facings` table) with:
- Crop thumbnail (bbox on shelf image)
- Predicted brand / product
- OCR text snippet + confidence
- **Edit** button

### 2. Correction modal

Fields:
- Brand (autocomplete from catalog)
- Product name
- Variant (optional)
- Pack text / OCR label (what is printed on pack)

On save:
- Update display inventory for this scan
- Append row to `scan_corrections` table (create if missing):

```sql
create table if not exists public.scan_corrections (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id),
  scan_id text not null,
  x1 int, y1 int, x2 int, y2 int,
  corrected_brand text,
  corrected_product text,
  corrected_ocr_label text,
  predicted_brand text,
  predicted_product text,
  pack_text text,
  category text,
  sub_category text,
  created_by uuid references auth.users(id),
  created_at timestamptz default now()
);
```

### 3. Export for training (admin)

Settings → **Export corrections** button:
- Downloads JSON array of corrections for backend import
- Backend runs: `py scripts/import_corrections_to_manifest.py corrections.json --create-case`

### 4. Metrics tooltip (already spec'd)

Clarify:
- **Avg AI confidence** = label confidence (not planogram compliance)
- **Planogram compliance** = SKU presence vs planogram

## Do not

- Re-draw annotated shelf on canvas (use backend JPEG)
- Block scan completion on corrections (async improvement loop)

## Success criteria

- User can fix a wrong Lay's flavor or tea brand in <30 seconds
- Corrections exportable as JSON for benchmark expansion
- "Needs review" count visible on scan results header
