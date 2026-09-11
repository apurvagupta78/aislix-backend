# Pilot Scorecard

Measure whether Aislix delivers **trustworthy, actionable shelf intelligence per capture** — not KPI card count.

---

## Primary outcomes

| Metric | Definition | Target (pilot) |
|--------|------------|----------------|
| First useful result time | Upload → supported observations visible | &lt; 60s p95 |
| Cost per usable audit | Platform + labor + review / usable completed audits | Decreasing vs baseline |
| First-pass usable capture rate | Scans not requiring rescan | ≥ 70% |
| Verification success rate | Confirmed fixes after rescan | ≥ 80% |
| Correction burden | Review minutes per audit | Decreasing |

---

## Trust & integrity (must pass)

| Check | Pass criteria |
|-------|---------------|
| Scope consistency | Category share denominator matches documented scope |
| Status consistency | No “0%” when status is `not_configured` |
| Unclassified handling | Unknown facings not counted as brands |
| Execution score gate | Score withheld when &lt;80% assessable weight |
| Financial honesty | MRP-only never labeled as net revenue/profit |
| Label accuracy | “Visible facings” not “inventory units” |

**Regression:** `pytest tests/test_colgate_regression_fixture.py tests/test_retail_execution_integrity.py`

---

## Operational execution

| Metric | Definition |
|--------|------------|
| Open action resolution time | confirmed → verified |
| Overdue action rate | past due / total open |
| Recurrence rate | Same root issue reopened within 14 days |
| Deduplicated issue count | Unique root causes vs raw alert count |

---

## Financial (when inputs configured)

| Metric | Definition |
|--------|------------|
| Estimated exposure accuracy | Modeled vs POS (where measurable) |
| Recoverable vs gross ratio | Disclosed assumptions |
| Double-count audit | Sum of ledger entries ≤ category demand cap |

**Scenario fixture:** INR 500 gross / 250 net revenue / 50 contribution — must match `financial-model.md`.

---

## Verified business outcomes (Tier D)

Prefer **difference-in-differences**:

(Treatment_post − Treatment_pre) − (Control_post − Control_pre)

Account for promotions, holidays, store hours, concurrent interventions.

Before/after photos → physical verification only, not sales causality.

---

## Pilot stores minimum data

Per store/bay:

- [ ] Audit sub-category and ROI defined  
- [ ] Assortment/planogram version ID  
- [ ] At least one rescan after corrective action  
- [ ] Capture timestamps and timezone  
- [ ] Optional: POS velocity for financial scenarios  

---

## Scorecard review cadence

- **Weekly:** Trust checks, action resolution, capture quality  
- **Monthly:** Cost per audit, verification success, financial scenario calibration  
- **Quarterly:** DiD or matched-control sales outcomes (if POS linked)  

---

## Exit criteria for GA trust milestone

1. All Phase 1 regression tests green  
2. Zero contradictory KPI states in UI/export for pilot cohort  
3. Executive summary generated from canonical metrics only  
4. Documented capture limitations shown in product (not docs only)  
5. At least one customer-verified before/after rescan workflow complete
