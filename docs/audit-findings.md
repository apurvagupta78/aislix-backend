# Forensic Audit Findings — Colgate / Max Fresh Scan (Sep 2026)

**Scope:** Screenshot-based reconstruction of a single scan shown across four role tabs.  
**Not verified:** Live website, original photograph, production database row, or competitor pricing.

---

## Finding 1 — Category-facing share uses full-image denominator

| Field | Detail |
|-------|--------|
| **Symptom** | Colgate facing share reported as 36.2% (42 ÷ 116). |
| **Evidence** | Report shows 116 total facings; mouthwash (6) and water (6) visible in same frame. |
| **Likely cause** | Brand share computed over all detected facings, not eligible category scope. |
| **Root cause** | `brand_share()` did not exclude category mismatches when audit sub-category set. |
| **Severity** | High — misstates competitive position by ~4.2 pp. |
| **Affected calculations** | Brand share %, competitor intel, executive narrative. |
| **Fix** | `build_brand_share_payload()` with `eligible_category` scope; denominator 104. |
| **Regression test** | `tests/test_colgate_regression_fixture.py::test_colgate_share_in_category_is_40_4_not_36_2` |

**Correct arithmetic (fixture assumptions):**

- Full image: 42 ÷ 116 = **36.2%**
- Toothpaste eligible: 42 ÷ 104 = **40.4%**

---

## Finding 2 — “Unknown” counted as identified brand

| Field | Detail |
|-------|--------|
| **Symptom** | Report lists 9 brands including “Unknown”. |
| **Evidence** | Brand table shows Unknown 6 facings alongside named brands. |
| **Root cause** | Unknown bucket treated as brand in `unique_brands` and share tables. |
| **Severity** | Medium — inflates brand count; hides unresolved identity. |
| **Fix** | `is_unclassified_brand()`; separate `Unclassified` row; `identified_brand_count`. |
| **Regression test** | `test_unknown_is_not_an_identified_brand`, `test_brand_share.py` |

---

## Finding 3 — Facings labeled as inventory / quantity

| Field | Detail |
|-------|--------|
| **Symptom** | “Complete inventory”, column “QTY”, executive text implies stock counts. |
| **Evidence** | UI screenshots; export CSV headers. |
| **Root cause** | Legacy naming from early MVP. |
| **Severity** | High — overstates photo capability. |
| **Fix** | Rename to “Observed shelf products”, “Visible facings” (UI + exports). |
| **Regression test** | Manual UX review; export header assertions (frontend). |

---

## Finding 4 — Expected qty (15) conflated with facings / presence

| Field | Detail |
|-------|--------|
| **Symptom** | Target availability 0/1 while expected quantity 15 in form. |
| **Evidence** | Form shows Expected quantity 15; KPI shows 0/1. |
| **Likely cause** | Distinct fields (distinct products vs target facings vs on-hand units) merged. |
| **Severity** | High — financial and compliance KPIs use wrong baseline. |
| **Fix** | Separate expectation contract (`target_facings`, `target_on_shelf_units`, `expected_distinct_products`); trace CSV + manual entry. |
| **Regression test** | `test_max_fresh_oos_revenue_at_risk_uses_velocity_not_expected_qty` |

---

## Finding 5 — False stockout certainty

| Field | Detail |
|-------|--------|
| **Symptom** | “1 confirmed OOS”, Max Fresh 0% product share, missing target treated as absence. |
| **Evidence** | Blank SKU, product-family name “Max Fresh”, no verified canonical match. |
| **Root cause** | Not-detected mapped to confirmed absence without evidence model. |
| **Severity** | Critical |
| **Fix** | Stockout evidence states: `not_observed`, `suspected_shelf_gap`, `verified_shelf_absence`, `confirmed_inventory_stockout`. |
| **Regression test** | `tests/test_retail_execution_integrity.py` availability tests (extend). |

---

## Finding 6 — Contradictory KPI states (0% vs Not configured)

| Field | Detail |
|-------|--------|
| **Symptom** | Cards say “Not configured / Not scoreable”; narratives claim 0% compliance. |
| **Evidence** | Planogram compliance, facing compliance, placement panels in screenshots. |
| **Root cause** | Independent string generation in role tabs vs metric cards. |
| **Severity** | High — destroys trust. |
| **Fix** | Canonical KPI result object; `buildKpiMetrics()` + `computeRetailExecutionScore()` on frontend; `finalize_execution_score()` on backend. |
| **Regression test** | `test_execution_score_withheld_when_coverage_insufficient` |

---

## Finding 7 — Opaque execution score (7/100)

| Field | Detail |
|-------|--------|
| **Symptom** | Headline score 7/100 with most inputs unavailable. |
| **Evidence** | Planogram not scoreable; facing/placement not configured; single unresolved target. |
| **Root cause** | Missing KPIs treated as zero; no coverage gate. |
| **Severity** | Critical |
| **Fix** | Withhold score when &lt;80% of planned weight assessable; expose `withhold_reason`. |
| **Regression test** | `test_execution_score_withheld_when_coverage_insufficient` (backend + frontend) |

---

## Finding 8 — Recognition coverage vs accuracy

| Field | Detail |
|-------|--------|
| **Symptom** | “98.2% average model confidence” read as accuracy; 110/116 not labeled as coverage. |
| **Evidence** | KPI cards in screenshot. |
| **Severity** | Medium |
| **Fix** | Label `recognition_coverage_percent`; separate detection confidence from benchmark accuracy. |
| **Regression test** | `test_recognition_coverage_among_detections` |

---

## Finding 9 — Image quality 100/100

| Field | Detail |
|-------|--------|
| **Symptom** | Perfect quality score without task-specific basis. |
| **Severity** | Medium |
| **Fix** | Remove hardcoded scores; task-specific quality (detection vs OCR vs price tags). |
| **Status** | Partial — backend must not emit unsupported 100/100. |

---

## Finding 10 — Duplicate issues and ledger gaps

| Field | Detail |
|-------|--------|
| **Symptom** | Same placement/missing issues under multiple labels; ledger shows 1 entry for 12 placement issues. |
| **Severity** | Medium |
| **Fix** | Canonical issue/event ledger keyed by root cause; dedupe in action engine. |
| **Status** | Planned (P2 opportunity ledger exists; dedupe rules pending). |

---

## Finding 11 — Conflicting financial risk labels

| Field | Detail |
|-------|--------|
| **Symptom** | “High” operational risk vs “low risk” in financial impact column. |
| **Severity** | Medium |
| **Fix** | Financial column shows currency + range + horizon or “Not estimated”; separate operational priority. |
| **Regression test** | `test_max_fresh_oos_revenue_at_risk_uses_velocity_not_expected_qty` |

---

## Finding 12 — Input propagation (form → analysis)

| Field | Detail |
|-------|--------|
| **Symptom** | Screenshot proves form values visible; not proven persisted to analysis. |
| **Severity** | High |
| **Fix** | Trace Add product → API → DB → planogram → metrics; CSV/manual parity. |
| **Status** | Ongoing — see `implementation-plan.md`. |

---

## Screenshot regression fixture

**File:** `tests/test_colgate_regression_fixture.py`

| Metric | Expected |
|--------|----------|
| All-image facings | 116 |
| Toothpaste denominator | 104 |
| Colgate full-image share | 36.2% |
| Colgate toothpaste share | 40.4% |
| Recognition coverage | 94.8% |
| Identified brands (full image) | 8 |
| Identified brands (toothpaste) | 7 |

*Fixture assumptions documented here — do not overwrite production results.*
