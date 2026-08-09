# Lovable prompt: Category Mismatch / Compliance Alerts UI

Use this after the backend deploy that returns `compliance_alerts`, `subcategory_mismatches`, and `metrics.misplaced_products`.

## API fields (from POST `/scan` response)

```json
{
  "metrics": {
    "misplaced_products": 12,
    "subcategory_mismatch_skus": 3
  },
  "compliance_alerts": [
    {
      "id": "category-mismatch",
      "severity": "high",
      "category": "compliance",
      "title": "Category Mismatch Detected",
      "interpretation": "Likely Putaway / Shelf Placement Violation",
      "detail": "Soap audit: 12 facing(s) appear to belong to other sub-categories — Shampoo (8), Toothpaste (4).",
      "expected_sub_category_label": "Soap",
      "misplaced_facings": 12
    }
  ],
  "subcategory_mismatches": [
    {
      "brand": "Tresemme",
      "product_name": "Keratin Smooth Shampoo",
      "detected_sub_category_label": "Shampoo",
      "expected_sub_category_label": "Soap",
      "quantity": 4,
      "confidence": 0.94
    }
  ],
  "alerts": [ "...includes compliance alert as first item..." ],
  "inventory": [
    {
      "brand": "Tresemme",
      "compliance_status": "category_mismatch",
      "compliance_interpretation": "Likely Putaway / Shelf Placement Violation"
    }
  ],
  "annotated_image_base64": "... red boxes on mismatches ..."
}
```

## Dashboard — Compliance Alerts panel

Add a **primary alert card** on scan results when `compliance_alerts.length > 0`:

1. **Title (large):** `Category Mismatch Detected` — use `compliance_alerts[0].title` (do not paraphrase).
2. **Subtitle (operational):** `Likely Putaway / Shelf Placement Violation` — use `compliance_alerts[0].interpretation`.
3. **Body:** show `detail` (breakdown by detected sub-category).
4. **Severity styling:** red/orange border, warning icon — this is the **top AI alert** on the page (above low-stock alerts).
5. **Metric tile:** wire `metrics.misplaced_products` (currently shows dash) — label: **Misplaced facings**.

## Inventory table

- Add a **Compliance** column.
- Rows with `compliance_status === "category_mismatch"` show a red badge: **Category Mismatch Detected**.
- Tooltip or secondary text: **Likely Putaway / Shelf Placement Violation**.

## Annotated image

- Backend already draws **red bounding boxes** and `WRONG: {brand}` labels on mismatches.
- Display the backend `annotated_image_base64` as-is (no client-side re-labeling).

## PDF download

- Backend PDF already includes a **Category Mismatch Detected** section with the operational interpretation and mismatch table.
- No frontend PDF changes required unless you generate PDFs client-side.

## Persist on scan record

Store on the scan row in Supabase:

- `compliance_alerts` (jsonb)
- `subcategory_mismatches` (jsonb)
- `misplaced_products` (integer, from metrics)

## CSV export (Export CSV button + download)

The inventory table **Export CSV** button currently builds CSV client-side via `inventoryToCsv()`
and does NOT include compliance columns. Fix both paths:

### Option A (preferred): use backend CSV

On scan complete, store `result.csv_base64` via `storeCsvReport` (see LOVABLE_DOWNLOAD_FIX_PROMPT.md).
Export CSV / download buttons should fetch stored `csv_url` when available — backend CSV includes:

`Brand, Product, Variant, Category, Quantity, Confidence %, Compliance Alert, Compliance Note, Detected Sub-category, Audit Sub-category, Stock Status`

- **Compliance Alert:** `Category Mismatch Detected` or `OK`
- **Compliance Note:** `Likely Putaway / Shelf Placement Violation` (empty when OK)

### Option B: fix client-side inventoryToCsv fallback

Update `inventoryToCsv(inventory)` to append these columns from each row:

```typescript
function inventoryToCsv(inventory: InventoryRow[]): string {
  const headers = [
    "Brand", "Product", "Variant", "Category", "Quantity", "Confidence %",
    "Shelf position", "Compliance Alert", "Compliance Note",
    "Detected Sub-category", "Audit Sub-category",
  ];
  const rows = inventory.map((row) => [
    row.brand ?? "",
    row.product_name ?? row.name ?? "",
    row.variant ?? "",
    row.category ?? "",
    String(row.quantity ?? row.facings ?? 0),
    String(Math.round(Number(row.confidence ?? 0) * 1000) / 10),
    row.shelf_position ?? "",
    row.compliance_alert ?? (row.compliance_status === "category_mismatch"
      ? "Category Mismatch Detected"
      : "OK"),
    row.compliance_interpretation ?? "",
    row.detected_sub_category_label ?? "",
    row.expected_sub_category_label ?? "",
  ]);
  return [headers, ...rows]
    .map((line) => line.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(","))
    .join("\n");
}
```

Ensure `inventory` / `products` saved from scan response includes:
`compliance_alert`, `compliance_interpretation`, `detected_sub_category_label`, `expected_sub_category_label`

## Copy constants (keep in sync with backend)

| Key | Value |
|-----|-------|
| Primary alert | **Category Mismatch Detected** |
| Interpretation | **Likely Putaway / Shelf Placement Violation** |

Use these exact strings anywhere the auditor sees compliance messaging (dashboard, scan history, email summaries).

## Test checklist

1. Run Personal Care + **Soap** on a mixed shelf photo.
2. Confirm primary alert shows **Category Mismatch Detected**.
3. Confirm subtitle shows **Likely Putaway / Shelf Placement Violation**.
4. Shampoo/toothpaste rows flagged in inventory; soap rows show OK.
5. Annotated image shows red boxes on mismatches only.
