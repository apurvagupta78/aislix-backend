# KPI Dictionary

Every KPI returns a typed result: `value | null`, `status`, `numerator`, `denominator`, `scope`, `formula_version`, `prerequisites`, `warnings`.

**Statuses:** `ready` | `partial` | `needs_configuration` | `needs_review` | `not_observable` | `not_applicable` | `stale` | `error`

**Rule:** `null` = unavailable. `0` only when evidence supports zero.

---

## 1. Visible facings

**ID:** `visible_facings`  
**Definition:** Count of deduplicated, supported front-facing product observations.  
**Scope:** `full_image` | `selected_bay` | `eligible_category`  
**Not:** Total inventory, units behind front row, backroom stock.

---

## 2. Visual product groups / identified SKUs

**ID:** `visual_product_groups` / `identified_skus`  
**Definition:** Distinct groups at the identification level achieved (category, brand, product family, exact SKU).  
**Note:** “Toothpaste / Original” is a visual group until canonical GTIN/SKU is established.

---

## 3. Identified brands

**ID:** `identified_brand_count`  
**Formula:** Count distinct brand names excluding unclassified buckets (`Unknown`, `Unclassified`, etc.).  
**Not:** Treating unresolved facings as a brand.

---

## 4. Recognition coverage

**ID:** `recognition_coverage_percent`  
**Formula:** `identified_facings / detected_eligible_facings × 100`  
**Not:** Detection recall, benchmark precision/recall, or sales accuracy.  
**Implementation:** `app/metrics.py::compute_metrics`

---

## 5. Facing share (brand)

**ID:** `brand_share_percent`  
**Formula:** `brand_facings_in_scope / all_facings_in_same_scope × 100`  
**Scope:** Must match denominator definition (`eligible_category` excludes category mismatches).  
**Unclassified:** Remain in denominator; shown as separate `Unclassified` row — do not renormalize only recognized brands.  
**Not:** Sales market share.

**Colgate fixture:**

- Full image: 42/116 = 36.2%
- Toothpaste: 42/104 = 40.4%

---

## 6. Product facing share

**ID:** `product_share_percent`  
**Formula:** `exact_product_facings / eligible_category_facings × 100`  
**Requires:** Canonical product match — family-name-only targets produce `needs_review`, not 0% absence.

---

## 7. Target presence / photo-assessed availability

**ID:** `target_sku_availability`  
**States:** P = present, A = verified absent, U = unresolved, T = P+A+U  
**Display:**

- Observed presence: P/T
- Assessment coverage: (P+A)/T
- Lower bound: P/T; upper bound: (P+U)/T

Point percentage only when coverage requirements met.

---

## 8. Stockout evidence

| State | Meaning |
|-------|---------|
| `not_observed` | Outside capture or insufficient coverage |
| `suspected_shelf_gap` | Visual gap, identity uncertain |
| `verified_shelf_absence` | Adequate coverage, product not detected |
| `confirmed_inventory_stockout` | Operational/inventory evidence |

Missing photo detection alone → max `suspected_shelf_gap` or `not_observed`.

---

## 9. Assortment compliance

**Observed breadth:** Distinct products at stated identification level.  
**Compliance:** `present_expected / eligible_expected` with unresolved coverage disclosed.  
**Requires:** Expected assortment list — cannot infer from detections alone.

---

## 10. Planogram SKU presence

**Formula:** Expected product membership observed / expected product membership.  
**Not:** Full spatial planogram compliance.

---

## 11. Facing fulfillment

**Formula:** `Σ min(observed_i, target_i) / Σ target_i`  
**Also expose:** target gap, min gap, excess count, within-range compliance.  
**Rule:** Over-facing one SKU does not offset missing another.

---

## 12. Placement / category intrusion

**Requires:** Physical zone or sequence expectation.  
**Category intrusion:** Non-category product inside designated zone.  
**Not:** Flagging adjacent-bay products at frame edge as misplaced.  
**Denominator:** Intrusion uses zone facings, not full-image facings.

---

## 13. Execution score

**ID:** `shelf_execution_score`  
**Formula:** `100 × Σ(weight_j × component_j) / Σ(assessed_weight_j)`  
**Gate:** Withhold if assessed weight &lt; 80% of planned profile weight.  
**Excluded from score:** Recognition coverage, image quality, brand share (unless configured as objective).  
**Not:** Comparable across incompatible profiles or coverage levels.

**Default weights (with planogram):** Availability 25, Planogram 20, Facing 15, Placement 15, Share 10.

---

## 14. Image quality

**Task-specific:** Detection adequacy, OCR readability, price-tag resolution — spatially aware.  
**Not:** Hardcoded 100/100 or conflated with shelf presentation.

---

## 15. Price execution

**Components:** Tag presence, readability, SKU-tag association, value correctness, promo/date validity.  
**MRP check:** Jurisdiction-configured; discount below MRP ≠ automatic noncompliance.

---

## How calculated (UI)

Each card links to:

1. Scope and denominator definition  
2. Numerator/denominator counts  
3. Exclusions (category mismatch, out-of-ROI)  
4. Formula version and timestamp  
5. Missing prerequisites  

Example facing share drawer:

> 42 identified Colgate facings ÷ 104 eligible toothpaste facings.  
> Excluded: 6 mouthwash and 6 water facings (category mismatch).
