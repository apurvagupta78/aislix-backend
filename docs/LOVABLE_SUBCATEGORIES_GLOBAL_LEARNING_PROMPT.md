# Lovable Prompt — Subcategories, Global Learned SKUs, GPT Stats

Paste into Lovable after backend deploy.

---

```
Implement subcategories on the scan form, global learned SKU catalog, and GPT usage display.

Backend: https://aislix-backend-production.up.railway.app
GET /categories now returns subcategories[] per category.

## A. Subcategory UI

1. On new scan form, after Category dropdown:
   - Fetch GET /categories (or use cached list)
   - Show Subcategory dropdown populated from selected category.subcategories[]
   - Required when category has subcategories (all except skip if loading)

2. When subcategory.id === "others":
   - Show text input: "Describe shelf type" (required)
   - Send value as sub_category_custom

3. When top-level category === "Others":
   - Hide subcategory dropdown
   - Only show "Describe shelf type" text input (required)
   - Send category: "Others", sub_category: "others", sub_category_custom: user text

4. POST /scan JSON body must include:
   {
     "category": "Personal Care",
     "sub_category": "soap",
     "sub_category_label": "Soap",
     "sub_category_custom": "",
     ...
   }

5. Scan results header show: "Personal Care · Soap · A-1-S"
   Read sub_category_label from result.scan_context or stored scan metadata.

## B. Global learned SKUs (dual-write)

Run SQL migration: supabase/migrations/20260809180000_global_learned_skus.sql

1. persistLearnedUpdates() in scan-pipeline.server.ts:
   - Keep upsert to learned_skus (org_id, sku) for audit
   - ALSO upsert to global_learned_skus (onConflict: sku) — no org_id

2. loadLearnedCatalog():
   - SELECT * FROM global_learned_skus ONLY (not filtered by org_id)
   - Send as learned_catalog in POST /scan

3. LearnedCatalogBadge total count: COUNT from global_learned_skus

4. Backfill already in migration SQL — verify global_learned_skus has rows after deploy

## C. GPT usage on scan results

From result.metrics display a small "Recognition breakdown" card:
- gpt_vision_calls — label "ChatGPT API calls"
- recognition_gpt — "Products labeled by GPT"
- recognition_learned — "From learned catalog"
- recognition_ocr — "Read from pack"
- recognition_unknown — "Unknown"

Store metrics in scan_results JSON so history shows GPT calls too.

## Acceptance
- Personal Care + Soap scan sends sub_category=soap
- Snickers / Figaro should not appear on Personal Care scans
- Learned catalog count identical across Test and Test 23 stores
- GPT call count visible on scan results page
```
