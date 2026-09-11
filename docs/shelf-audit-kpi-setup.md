# Shelf Audit KPI System — Setup & Usage

## Overview

Aislix now computes **five role-specific primary KPIs** per audit using deterministic backend code (`app/audit_kpi_engine.py`). AI observations feed evidence; KPI arithmetic never comes from the model.

### Roles and KPIs

| Role | Primary KPIs |
|------|----------------|
| Supermarket | OSA, Planogram Compliance, Assortment, Price, Promotional |
| Dark Store | OSA, Location Accuracy, Planogram, Assortment, Facing Count |
| FMCG Brand | Share of Shelf, OSA, Facing Count, Planogram, Promotional |
| Distributor | OSA, MSL Compliance, Planogram, Price, Promotional |
| Local Store | OSA, Assortment, Facing Count, Price, Promotional |

Each KPI returns: `value`, `status`, `numerator`, `denominator`, `coverage_percent`, `formula`, and warnings.

## Planogram import

### Products CSV (required)

Template header:

```text
location,category,sub_category,brand,product_name,variant,expected_facings,min_facings,max_facings,expected_shelf_units,mrp_inr,avg_daily_sales,sku,shelf_position
```

**Required:** location, category, sub_category, brand, product_name, and **either** `expected_facings` **or** `expected_qty`.

Download template: `GET /planogram/csv-template`

Validate: `POST /planogram/parse-csv`

### Extended audit package (optional JSON on `planogram_versions.audit_package`)

```json
{
  "assortment_skus": [...],
  "msl_skus": [...],
  "promotions": [...],
  "sos_geometry": { "calibrated": true, "basis": "linear_shelf_length" },
  "primary_brand": "Colgate"
}
```

Optional CSV supplements in `data/demo/oral_care/`:
- `assortment_msl.csv`
- `promotions.csv`

Missing optional data → affected KPIs show **Not configured**, never fabricated zeros.

## Running tests

```bash
py -3 -m pytest tests/test_audit_kpi.py -q
py -3 -m pytest tests/test_planogram_compliance.py -q
```

Spec numerical tests (OSA 90%/80% coverage, planogram 84%, etc.) are in `tests/test_audit_kpi.py`.

## Scan results UI

After a scan completes, `metrics.retail_intelligence.audit_kpi_dashboard` drives the five KPI cards on `/results` with coverage labels and status badges.

Set organization **customer type** in onboarding/settings to select the role profile.

## Demo data

Hypothetical oral-care fixture: `data/demo/oral_care/` — clearly labeled demo SKUs, not real photograph measurements.

## Remaining limitations

- **Linear Share of Shelf** requires calibrated geometry; bbox-width proxy used until fixture dimensions supplied.
- **Promotional compliance** requires promotion rules in audit package.
- **Manual annotation UI** for bounding-box correction — existing review queue; full CVAT-style editor not yet built.
- **Side-by-side planogram heatmap** — table comparison exists; visual shelf grid pending.
- **Immutable planogram version history** — DB supports versions; full diff UI pending.

## AI provider

Configure vision credentials in server environment. Without AI, manual review and demo-labeled audits still work — never silently substituted as real analysis.
