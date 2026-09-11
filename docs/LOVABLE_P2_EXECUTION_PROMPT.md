# Lovable Prompt — P2 Retail Execution Intelligence

Implement **P2** frontend surfaces for audit scope, pricing compliance, multi-photo bay audits, planogram versioning, and persistent execution workflow. Backend (`aislix-backend` on Railway) already returns these fields in `metrics` and `retail_intelligence`.

---

## Backend fields to consume

### `metrics.audit_scope`
```json
{
  "audited_sub_category": "toothpaste",
  "in_scope_facings": 42,
  "adjacent_bay_facings": 3,
  "background_facings": 1,
  "total_facings": 46,
  "state": "available"
}
```

### `metrics.adjacent_category_findings[]`
Informational only — do **not** penalize execution score. Show as “Adjacent category (excluded from placement KPI)”.

### `metrics.multi_photo` (when scan metadata includes `additional_photos`)
```json
{
  "photo_count": 2,
  "merged_facings": 38,
  "facings_per_photo": [20, 21]
}
```

### `retail_intelligence.pricing`
- `state`: `not_configured` | `not_observable` | `available`
- `compliance_percent` — MetricValue with state
- `lines[]`: `{ brand, product, expected_price_inr, detected_price_inr, variance_inr, status }`

### `retail_intelligence.audit_scope` — same as metrics block

---

## 1. Audit scope UI (scan results)

On **Execution** / **Retail Intelligence** tab:

1. **Bay scope badge** near shelf summary:
   - “Auditing: {sub_category}”
   - “In-scope facings: N · Adjacent: M (informational)”

2. **Adjacent category panel** (collapsible):
   - List `adjacent_category_findings` with brand/product and reason (`frame_edge_adjacent_category` vs `category_mismatch`)
   - Copy: “These facings are excluded from placement compliance — they appear to belong to a neighboring category or bay edge.”

3. **Placement KPI tooltip**: “Placement compliance counts only in-scope facings in the audited bay.”

---

## 2. Pricing compliance panel

New card **Price tag compliance** under Retail Intelligence:

| State | UI |
|-------|-----|
| `not_configured` | “Configure MRP on planogram rows to enable price checks.” |
| `not_observable` | “Price tags not readable in this image.” |
| `available` | Show compliance % + table of lines (expected vs detected vs variance) |

Use `formatMetricValue` pattern from other KPI cards. Non-compliant rows: highlight variance in amber/red.

---

## 3. Multi-photo bay audit (scan upload)

**Scan form** — optional “Add another photo of same bay”:

1. Allow 2–4 photos before submit (burst mode).
2. Send to Railway `POST /scan`:
   ```json
   {
     "image_urls": ["primary.jpg", "photo2.jpg"],
     "additional_photos": [
       { "image_url": "photo2.jpg" }
     ],
     "metadata": { "multi_photo_mode": "bay_burst" }
   }
   ```
3. On results, if `metrics.multi_photo` present, show: “Merged {photo_count} photos · {merged_facings} facings after dedupe.”

4. **Verify rescan** flow (`/scan?verify={scanId}`): pre-fill store/shelf/subcategory; allow multi-photo again.

> Note: Full per-photo YOLO merge on backend requires classified batches in metadata today; primary + future photos can be wired incrementally. UI should still support multi-upload for forward compatibility.

---

## 4. Planogram versioning (Store Master)

Extend **Planogram / Store Master**:

### DB (apply migration `20260911120000_p2_execution_intelligence.sql`)
- `planogram_items.expected_facings`, `min_facings`, `max_facings`, `expected_shelf_units`
- `planogram_versions.effective_from`, `effective_to`, `store_format`

### UI
1. Version editor fields: **Effective from**, **Effective to**, **Store format** (dropdown: Hypermarket, Supermarket, Kirana, Dark store, Other).
2. When activating a version, set `effective_from = now()` and archive prior active version’s `effective_to`.
3. Scan assignment: pick **active version for store** at assignment time; store `planogram_version_id` on assignment (already exists).

4. CSV import/export: include `expected_facings`, `min_facings`, `max_facings`, `expected_shelf_units`, `mrp_inr`, `avg_daily_sales`.

---

## 5. Execution workflow persistence

New tables: `execution_opportunities`, `execution_actions`.

### After scan completes (server action or edge function):
1. Read `retail_intelligence.opportunity_ledger[]` from scan result.
2. Upsert rows into `execution_opportunities` for the org/scan.
3. Status enum: `open`, `assigned`, `in_progress`, `fixed`, `rescan_required`, `verified`, `dismissed`, `closed`.

### Manager UI — “Execution queue” (optional nav item):
- Filter by store, priority, status
- Assign to team member → `assigned_to`, status `assigned`
- Mark fixed → status `fixed`, insert `execution_actions` row
- Link **Rescan to verify** → new scan with `parent_scan_id` + `metadata.verify_scan_id`

### Verified badge
When follow-up scan has `parent_scan_id` and `retail_intelligence.execution_verification.verified === true`, show verified state on both scans.

---

## 6. KPI integrity rules (do not regress P0/P1)

- **Unknown / Unclassified** brands → never in competitor share chart
- **Revenue at risk** = `avg_daily_sales × mrp_inr` (not expected facings × price)
- **Execution score** → “Not scoreable” when KPI coverage insufficient
- **Facing compliance** → only when planogram has `expected_facings`
- **Presentability** → “Not assessed” (no heuristic score)

---

## 7. QA checklist

- [ ] Toothpaste scan with water bottle on left edge → adjacent finding shown, placement KPI not tanked
- [ ] Planogram with MRP + readable pack text → pricing panel shows compliance
- [ ] Multi-photo upload → results show merged photo count
- [ ] Planogram version activate/archive with effective dates
- [ ] Opportunity ledger persists to `execution_opportunities` after scan
- [ ] Fix → rescan → verify shows before/after on second scan

---

## Files likely to touch

- `src/components/scan-results/RetailIntelligencePanels.tsx` — pricing + audit scope panels
- `src/components/scan-results/ExecutionPhase1.tsx` — scope badge
- `src/routes/scan.tsx` — multi-photo upload
- `src/components/planogram/PlanogramBuilder.tsx` — version metadata (partially done in P1)
- `src/lib/planogram-library.ts` — versioning CRUD
- `src/lib/scan-pipeline.server.ts` — persist opportunities + parent_scan_id
- Supabase types regeneration after migration
