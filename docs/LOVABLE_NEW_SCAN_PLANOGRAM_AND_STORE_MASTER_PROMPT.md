# Lovable Prompt — New Scan optional planogram + Store Master Step 2 field schema

Paste into Lovable chat, then **Publish**.

**Backend (Railway):** deploy latest `main` — includes `/planogram/csv-template`, stricter CSV validation, `variant` field.

**Supabase:** run migration `supabase/migrations/20260813120000_planogram_variant.sql` in Lovable Cloud SQL.

---

```
NEW SCAN + STORE MASTER — planogram upload UX and Step 2 field schema

Two related changes. Implement BOTH in one pass.

══════════════════════════════════════════════════════════════
CHANGE 1 — New Scan page: OPTIONAL planogram upload
══════════════════════════════════════════════════════════════

On the New Scan page (/scan/new or equivalent), add an OPTIONAL section:

  "Expected shelf planogram (optional)"
  Subtext: "Upload expected products for this shelf to get compliance % after scan.
            Skip if you only want inventory detection."

Reuse the SAME UI components as Store Master Step 2 (Planogram page):
  - Tab A: Upload CSV
  - Tab B: Add manually (row-by-row)
  - Preview table for parsed rows
  - Inline validation errors (persistent Alert — not auto-dismiss toast)

Behavior:
  - Section is COLLAPSED by default with a toggle: "Add expected planogram"
  - User can start scan WITHOUT planogram (free scan) — unchanged
  - If user adds planogram rows (CSV or manual), include them in POST /scan metadata:
      planogram_items: normalized rows from preview
      planogram_items_full: same rows (or full store list if loaded from active planogram)
  - Do NOT require saving to Store Master / planogram_versions for ad-hoc scan planograms
  - If store has an active planogram, show helper link:
      "Use active store planogram instead" → pre-fill from Supabase planogram_items

CSV upload on New Scan:
  POST {VITE_AISLIX_API_URL}/planogram/parse-csv  (same as Store Master)
  Template download:
    GET {VITE_AISLIX_API_URL}/planogram/csv-template
    → use response.csv_text for "Download template" button

Manual row on New Scan:
  POST {VITE_AISLIX_API_URL}/planogram/normalize-row before adding to preview list

When planogram rows present, show badge on scan button:
  "Assigned-style scan · N expected products"

══════════════════════════════════════════════════════════════
CHANGE 2 — Store Master Step 2: field schema + CSV columns
══════════════════════════════════════════════════════════════

Update Store Master → Step 2 (Planogram / Expected Data) manual form AND CSV template.

FIELD ORDER (manual form columns left-to-right):

  1. Location          — REQUIRED  (shelf/aisle code e.g. "A-1-Z" — NOT the store name)
  2. Category          — REQUIRED
  3. Sub category      — REQUIRED  (dropdown from /categories where available)
  4. Brand             — REQUIRED
  5. Product Name      — REQUIRED
  6. Variant           — OPTIONAL  (NEW — pack size / flavor, e.g. "340ml", "25 bags")
  7. Expected qty      — REQUIRED  (number >= 0)
  8. SKU               — OPTIONAL
  9. Shelf Position    — OPTIONAL

Remove or de-emphasize separate "Aisle" field in the UI if it duplicates Location.
(Backend still accepts legacy `aisle` column in CSV for old files — do not show as primary field.)

Validation:
  - Block Save / Add row if any required field empty
  - Call POST /planogram/normalize-row on manual add — show API errors inline under form
  - Mark required fields with asterisk (*)

CSV template (download + docs) — exact header order:

  location,category,sub_category,brand,product_name,variant,expected_qty,sku,shelf_position

Required CSV columns (upload rejected if missing):
  location, category, sub_category, brand, product_name, expected_qty

Optional CSV columns:
  variant, sku, shelf_position

Example row:
  A-1-Z,Personal Care,Shampoo,Dove,Intense Repair Shampoo,340ml,1,,1

Preview table columns should match the 9 fields above (hide legacy aisle unless present in CSV).

Supabase insert — include new column on planogram_items:
  variant: row.variant || null

Apply migration 20260813120000_planogram_variant.sql:
  - ADD COLUMN variant TEXT
  - location + sub_category NOT NULL (backfill runs in migration)

Update TypeScript types:
  PlanogramItem { location, category, sub_category, brand, product_name, variant?, expected_qty, sku?, shelf_position?, match_key? }

══════════════════════════════════════════════════════════════
SHARED — CSV error handling (both pages)
══════════════════════════════════════════════════════════════

Same pattern as LOVABLE_PLANOGRAM_CSV_ERROR_PROMPT.md:
  - Persistent red Alert for upload/validation failures (not 3s toast)
  - Show row-level errors in preview table
  - Distinguish network errors from validation errors (200 OK with error_count)

Required column missing → show:
  "Missing required column: location" (etc.)

══════════════════════════════════════════════════════════════
TEST CHECKLIST
══════════════════════════════════════════════════════════════

New Scan:
1. Scan without planogram → works (free scan, no compliance block)
2. Expand optional planogram → upload valid CSV → preview → scan includes planogram_items
3. Manual add row missing location → inline error, cannot add
4. Download template → header matches 9-column schema

Store Master Step 2:
5. Manual form shows 9 fields in order; variant optional
6. Cannot save row without location, category, sub_category, brand, product_name, expected_qty
7. CSV missing sub_category column → persistent error alert
8. Valid CSV with variant column → saves variant to planogram_items
9. Activate planogram → assign scan still works with new schema

Publish when done.
```

---

## Backend reference

| Endpoint | Purpose |
|----------|---------|
| `GET /planogram/csv-template` | Template header + example row |
| `POST /planogram/parse-csv` | Validate CSV upload |
| `POST /planogram/normalize-row` | Validate single manual row |
| `POST /scan` | Pass `planogram_items` in JSON body for compliance |

Required fields enforced by backend: `location`, `category`, `sub_category`, `brand`, `product_name`, `expected_qty`.

Optional: `variant`, `sku`, `shelf_position`, `aisle` (legacy).
