# KPI Trust & Integrity — Implementation Plan

**Goal:** Trustworthy shelf observations → scoped KPIs → deduplicated actions → honest financial estimates.

**Principle:** Optimize trust, actionability, simplicity, and ROI — not dashboard card count.

---

## Phase 0 — Documentation & fixture (complete)

- [x] `docs/audit-findings.md` — forensic findings with evidence
- [x] `docs/kpi-dictionary.md` — metric definitions
- [x] `docs/financial-model.md` — auditable finance contract
- [x] `docs/competitive-benchmark.md` — vendor research (partially verified)
- [x] `docs/capture-limitations.md` — capability tiers A–D
- [x] `docs/pilot-scorecard.md` — closed-loop measurement
- [x] Colgate regression fixture + tests

---

## Phase 1 — Canonical calculation layer (in progress)

### Backend (`app/metrics.py`)

| Item | Status |
|------|--------|
| Category-scoped brand share (`eligible_category`) | Done |
| Unclassified brand separation | Done |
| Execution score 80% coverage gate | Done |
| `finalize_execution_score()` | Done |
| `apply_brand_share_to_metrics()` | Done |
| Executive summary without false certainty | Done |
| Wire `finalize_execution_score` in pipeline post-process | Partial |

### Frontend (`aislix-frontend`)

| Item | Status |
|------|--------|
| Rename inventory → observed shelf products | Done |
| Visible facings column label | Done |
| `buildKpiMetrics()` explicit states | Exists |
| `computeRetailExecutionScore()` coverage gate | Exists |
| Brand share denominator drill-down in UI | Pending |
| Single canonical results view (role tabs) | Pending |

---

## Phase 2 — Expectation & input contract (in progress)

| Item | Status |
|------|--------|
| CSV parses `expected_facings`, `min/max_facings`, `expected_shelf_units` | Done |
| DB migration `audit_package` + extended planogram columns | Done |
| Role-based 5-KPI audit engine (`app/audit_kpi_engine.py`) | Done |
| Frontend role KPI strip with coverage badges | Done |
| Separate `authorized_shelf_price` vs MRP in UI forms | Pending |
| Full planogram editor tabs (assortment, promotions, scoring) | Pending |
| JSON import/export for complete planogram package | Pending |

**Files:** `app/planogram*.py`, `app/audit_kpi_*.py`, frontend `role-kpi-config.ts`, `execution-metrics.ts`

---

## Phase 3 — Evidence model & availability

1. Stockout states: `not_observed` → `suspected_shelf_gap` → `verified_shelf_absence` → `confirmed_inventory_stockout`.

2. Photo-assessed availability bounds: P/T, (P+A)/T, (P+U)/T.

3. Never map “not detected” to confirmed OOS without coverage + identity confidence.

4. Blank SKU → identity resolution workflow, not automatic absence.

**Files:** `app/retail_execution.py`, `app/subcategory_compliance.py`

---

## Phase 4 — Action engine & ledger deduplication

1. Stable issue IDs: tenant + store + bay + SKU/zone + root cause + interval.

2. Lifecycle: candidate → confirmed → assigned → fixed_pending_verification → verified.

3. One root absence → one ledger entry (not planogram + OOS + placement triple count).

4. Group intrusions: “Review 12 possible category intrusions” vs 12 duplicate alerts.

**Files:** `app/retail_execution.py`, `execution_opportunities` table, frontend Action Center.

---

## Phase 5 — Financial engine hardening

1. MRP-only → “MRP-valued demand exposure” scenario label.

2. Decimal/money-safe arithmetic for totals.

3. Substitution scenarios with disclosed assumptions (INR 500 / 250 / 50 fixture).

4. Non-double-counting rules across issue types and horizons.

5. Financial column: currency + amount/range or “Not estimated”.

**Files:** `app/metrics.py::compute_financial_impact`, new `app/financial_model.py` (optional extract).

---

## Phase 6 — UI simplification

1. Primary nav: Overview | Actions & evidence | Trends & value.

2. Max four primary KPI cards on overview; withhold unavailable metrics.

3. Annotated shelf image with scope/exclusion overlays.

4. KPI explanation drawer (“42 ÷ 104 eligible toothpaste facings”).

5. Deterministic executive summary (5 bullets max); LLM narrative validated against canonical metrics.

---

## Phase 7 — Exports & security

1. Workbook sheets: Summary, Observed products, Evidence, KPI definitions, Issues, Financial assumptions.

2. Same canonical values as UI; no facings under inventory-units column.

3. Spreadsheet formula injection prevention.

4. Tenant isolation regression tests.

---

## Testing matrix

| Suite | Covers |
|-------|--------|
| `test_colgate_regression_fixture.py` | Share scope, brand count, coverage |
| `test_brand_share.py` | Denominator exclusion |
| `test_retail_execution_integrity.py` | Finance, score gating |
| `test_p2_execution.py` | Audit scope, pricing, multi-photo |

Run: `py -m pytest tests/test_colgate_regression_fixture.py tests/test_retail_execution_integrity.py tests/test_brand_share.py tests/test_p2_execution.py`

---

## Feature flags

- `KPI_EXECUTION_SCORE_GATE` — enforce 80% coverage (default on)
- `FINANCIAL_SCENARIO_MODE` — require explicit inputs before showing amounts

---

## Dependencies not blocking contract

- POS/inventory integration → honest `not_applicable` states
- Price-tag OCR association → partial price compliance
- Offline inference → label correctly if unavailable
