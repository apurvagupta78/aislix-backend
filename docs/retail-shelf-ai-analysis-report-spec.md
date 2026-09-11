# Retail Shelf AI Analysis Report — Canonical Spec & Aislix Mapping

**Spec version:** 1.0  
**Report title:** RETAIL SHELF AI ANALYSIS REPORT  
**Aislix implementation:** `app/report_generator.py` (PDF + CSV v2, eight sections)

---

## Report header

| Field | Spec | Aislix source | Notes |
|-------|------|---------------|-------|
| Report ID | `[REPORT_ID]` | `scan_id` | UUID from `shelf_scans` |
| Status | `DRAFT` / `VALIDATED` | `report_context.status` | Default `DRAFT`; `VALIDATED` after human sign-off (future) |
| Analysis date | Capture / processing timestamp | Pipeline `datetime.now()` + stored `created_at` | Timezone: store-local when configured |
| System version | Analyst / model version | `model_version` in pipeline payload | e.g. `yolov8+ocr+faiss+clip+gpt-v2` |

---

## Section 1 — Purpose, scope and business context

| Spec field | Aislix source |
|------------|---------------|
| Business / site | `store_label` or `store_id` |
| Facility type | `customer_type` (`supermarket`, `dark_store`, `warehouse`, `distributor`, `fmcg_brand`) |
| Stakeholder | Derived from `customer_type` + workspace role |
| Location | `location` / `shelf_label` |
| Capture time | Scan `created_at` |
| Objectives | Tier A–B photo audit; planogram when configured |
| Analysis boundary | `metrics.audit_scope`, `scan_category`, `scan_sub_category` |
| Executive summary | `executive_summary` (`app/metrics.py`) |

**Rule:** Findings cover photographed, assessable locations only — not the entire facility.

---

## Section 2 — Inputs and analysis method

| Spec field | Aislix source |
|------------|---------------|
| Photo reference | Annotated + original image URLs / embedded JPEG in PDF |
| Site / location ID | `store_id`, `shelf_label` |
| Category / scope | `category`, `sub_category` |
| Image assessment | `retail_intelligence.image_quality` |
| Assessable area | `metrics.audit_scope.in_scope_facings`, adjacent-bay exclusions |
| Recapture required | Image quality score & warnings |
| Planogram reference | `planogram_compliance`, planogram version when assigned |
| Method | `detection_mode`, model stack in `model_version` |
| Evidence convention | `PHOTO-DETECTED` default; `USER-SUPPLIED` for planogram/prices |
| Missing-data rule | KPI `status` from `metric_states.py`; null ≠ zero |

See also: `docs/capture-limitations.md`, `docs/kpi-dictionary.md`.

---

## Section 3 — Shelf, location and reference fields

| Spec field | Aislix source |
|------------|---------------|
| Location hierarchy | Site → location → category → sub-category (full bay ID future) |
| Fixture | Assumed standard shelf unless configured |
| Coordinate system | Normalized image bbox `x1,y1,x2,y2` on inventory rows |
| Reference per slot | Planogram items: brand, product, expected_qty, shelf_position, mrp_inr |
| Placement rules | Sub-category compliance, planogram position (when configured) |

**Gap (planned):** Physical width/height calibration, slot-level numbering.

---

## Section 4 — Product and observation fields

Per inventory / facing record:

| Spec field | Aislix JSON field |
|------------|-------------------|
| Brand / product / variant | `brand`, `product_name`, `variant` |
| Category | `category`, `detected_sub_category_label` |
| Position | `shelf_position`, bbox coordinates |
| Facings / quantity | `quantity` (visible facings, deduplicated) |
| Confidence | `confidence` |
| Compliance | `compliance_status`, `compliance_alert` |
| Stock evidence | `stock_status` |
| Recognition source | `recognition_source` |
| Evidence type | `PHOTO-DETECTED` (+ source label) |

**Gap (planned):** OCR price on shelf labels, promotion execution, GTIN.

---

## Section 5 — Core calculations and KPIs

Each KPI in exports includes: **value, numerator, denominator, coverage, state, scope**.

| KPI (spec) | Aislix metric key | Implementation |
|------------|-------------------|----------------|
| Assessment coverage | `recognition_coverage_percent` | `compute_metrics` |
| Facing share of shelf | `brand_share_percent`, `share_of_shelf_percent` | Scoped via `brand_share_scope` |
| Linear share | — | `not_configured` (no calibration) |
| Shelf utilization | `shelf_utilization_percent` | When geometry available |
| Facing attainment | `planogram_qty_compliance_percent` | Planogram required |
| On-shelf availability | `availability_percent` / `osa_percent` | Planogram required |
| Shelf OOS rate | `confirmed_oos_count`, stockout evidence | `stockout_evidence.py` |
| Planogram compliance | `planogram_sku_match_percent` | Planogram match |
| Placement score | `placement_compliance_percent` | Sub-category rules |
| Price accuracy | `retail_intelligence.pricing` | OCR + reference prices |
| Execution score | `shelf_execution_score` | Withheld if coverage &lt; 80% |

Full definitions: `docs/kpi-dictionary.md`.

---

## Section 6 — Optional inventory, distribution and warehouse KPIs

| KPI | Aislix | Tier |
|-----|--------|------|
| Shelf capacity estimate | Not emitted | Requires calibration |
| Refill need | Partial via planogram qty gaps | B |
| Days of supply / reorder | Not from photo alone | D |
| Commercial impact | `financial_impact` | C — **indicative only**; requires user-supplied MRP + demand |

**Rule:** Financial rows labeled `ESTIMATED` / `indicative`; never implied as verified sales loss.

---

## Section 7 — Findings and corrective actions

| Spec field | Aislix source |
|------------|---------------|
| Action records | `recommendations`, `retail_intelligence.opportunity_ledger`, `next_best_actions` |
| Priority | `severity` / `priority` on actions |
| Evidence | Issue type + SKU/location |
| Expected benefit | `estimated_daily_impact_inr` when priced |

---

## Section 8 — Validation, limitations and supporting evidence

| Spec field | Aislix source |
|------------|---------------|
| Reconciliation | Dedup facings, scope checks in pipeline |
| Photo limitations | Static text from `capture-limitations.md` |
| Evidence package | Original photo, annotated image, this report, product table |
| Shelf diagram | Annotated image (bbox labels) |
| Enabled modules | Listed from configured planogram / pricing / financial inputs |
| Omitted modules | Linear share, WMS, POS, etc. with reason |

---

## Export surfaces

| Surface | Eight-section | Notes |
|---------|---------------|-------|
| Backend PDF | Yes | `generate_pdf_bytes` |
| Backend CSV | Yes | `generate_csv_bytes` |
| Frontend Excel | Partial | `buildFullScanReportExcel` — align in Phase 7 |
| Results UI | Yes | `ScanResultsBody` sections map to spec intent |

---

## Canonical spec text (reference)

### Section 1 — Purpose, scope and business context

- Business/site, facility type, stakeholder, location, capture time, analyst/system version.
- Objectives by stakeholder (FMCG visibility/compliance; retail availability/pricing; dark-store replenishment; warehouse accuracy).
- Analysis boundary: category / aisle / bay / bin IDs; photographed assessable locations only.
- Executive summary: key findings, top actions, confidence; distinguish verified vs needs inspection.

### Section 2 — Inputs and analysis method

- Required inputs: photo, site ID, location ID, category/scope.
- Image assessment: resolution, blur, glare, occlusion, cropping; recapture flag.
- Conditional references: planogram, assortment, catalog, price file.
- Conditional operational inputs: inventory/POS/WMS (Tier D).
- Method: detection → OCR → catalog match → reference match.
- Evidence: PHOTO-DETECTED / USER-SUPPLIED / SYSTEM-IMPORTED / ESTIMATED + confidence + region.
- Missing data: UNKNOWN / NOT ASSESSABLE / NOT APPLICABLE — never substitute zero.

### Sections 3–8

See user-provided master template (2026-09) — field-level mapping tables above tie each block to Aislix schema and code paths.

---

## Related documents

- `docs/kpi-dictionary.md` — formulas and statuses  
- `docs/capture-limitations.md` — Tier A–D capability model  
- `docs/implementation-plan.md` — Phase 7 export parity  
- `docs/pilot-scorecard.md` — sellability criteria  
