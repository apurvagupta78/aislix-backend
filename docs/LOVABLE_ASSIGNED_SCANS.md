# Lovable: Assigned Scans & Planogram Compliance (M1–M4)

Apply migrations from `supabase/migrations/20260811120000_assigned_scans_planogram.sql` in Lovable Cloud SQL first.

Backend endpoints (Railway):
- `POST /planogram/parse-csv` — CSV file or `{ "csv_text": "..." }`
- `POST /planogram/normalize-row` — validate single manual row
- `POST /planogram/compare` — `{ planogram_items, inventory, scan_context, scope_type, scope_values }`
- `POST /scan` JSON — add `assignment_id`, `planogram_items`, `assignment_scope_type`, `assignment_scope_values`

Scan response adds:
```json
{
  "planogram_compliance": {
    "compliance_percent": 82,
    "scan_status": "needs_attention",
    "summary": { "expected_products": 8, "missing_products": 2, ... },
    "lines": [...],
    "corrective_actions": [{ "issue_type": "missing", "suggestion": "...", "status": "open" }]
  },
  "metrics": { "planogram_compliance_percent": 82, "planogram_summary": {} },
  "assignment_id": "uuid"
}
```

Issue types: `correct`, `missing`, `qty_mismatch`, `wrong_product`, `wrong_category`, `wrong_location`, `unexpected`

Severity colors: green=correct, red=critical, yellow=warning, blue=info

---

## M1 — Store Master (Steps 1–2)

**Manager nav:** Store Master, Planogram / Expected Data

### Two input tabs
1. **Upload CSV** — call Railway `POST /planogram/parse-csv`, show preview table; highlight invalid rows
2. **Add manually** — form fields (in order):
   - **Required:** Location, Category, Sub-category, Brand, Product Name, Expected Qty
   - **Optional:** Variant, SKU, Shelf position
   - **Save & add another**

**Location** = shelf/aisle code (e.g. `A-1-Z`), not the store name.

**CSV template header:**
`location,category,sub_category,brand,product_name,variant,expected_qty,sku,shelf_position`

Download template: `GET /planogram/csv-template`

Both write to Supabase `planogram_items` under a `planogram_versions` row with `status=draft`.

### Unified table
- Editable rows (inline edit / delete)
- Mix CSV + manual rows (`source_type`: csv | manual | mixed)
- **Activate planogram** → set version `status=active`, archive prior active version for same store

### Supabase writes
```typescript
// Insert draft version
await supabase.from('planogram_versions').insert({ org_id, store_id, name, status: 'draft', source_type, uploaded_by })

// Bulk insert items with match_key from normalize-row or CSV preview
await supabase.from('planogram_items').insert(rows)

// Activate
await supabase.from('planogram_versions').update({ status: 'archived' }).eq('store_id', storeId).eq('status', 'active')
await supabase.from('planogram_versions').update({ status: 'active', activated_at: new Date() }).eq('id', versionId)
```

---

## M2 — Assign Scan + Notifications (Steps 3–4)

**Manager:** Assign Scan button on Store Master or Assigned Scans page

### Assign modal
- Scope tabs: **Category** | **Sub-category** | **Location/Aisle**
- Multi-select where applicable
- Assignee dropdown: `organization_members` where `role in ('member')` or all non-owner
- Due date (optional), instructions textarea
- Creates `scan_assignments` row

### Notifications
On insert assignment:
```typescript
await supabase.from('notifications').insert({
  user_id: assignee_id,
  org_id,
  type: 'scan_assigned',
  title: 'New Scan Assigned',
  body: `Store / ${aisle} / ${category}`,
  payload: { assignment_id }
})
```
Edge Function `notify-assignment` (optional): send email via Resend

### Junior nav: My Assigned Scans
- Tabs: Pending | In Progress | Completed | Overdue
- Card: store, aisle, category, sub-category, expected product count (from planogram_items filtered by scope), due date, assigner name, status

---

## M3 — Scan + Compare + Junior Results (Steps 5–7)

### Start Scan from assignment
Pre-fill scan metadata:
```typescript
{
  assignment_id,
  store_id,
  location, shelf_label,
  category, sub_category,
  assignment_scope_type: assignment.scope_type,
  assignment_scope_values: assignment.scope_values,
  planogram_items: filteredItems,  // from active planogram for scope
  planogram_items_full: allStoreItems  // for wrong-location checks
}
```

Update assignment `status=in_progress` on Start.

### After scan completes
1. Persist `shelf_scans.assignment_id`, `planogram_compliance_percent` from `metrics.planogram_compliance_percent`
2. Insert `planogram_comparisons` + `planogram_comparison_lines` from `planogram_compliance.lines`
3. Insert `corrective_actions` from `planogram_compliance.corrective_actions`
4. Update `detected_products.expected_facings` per matched row

### Junior results page
Summary tiles from `planogram_compliance.summary`:
- Expected Products, Products Found, Missing, Quantity Issues, Wrong Products, Wrong Category, Wrong Location, Unexpected
- Annotated image (existing)
- Table: Expected | Actual | Status | Issue (color-coded)
- **Submit scan** → assignment `status=completed`, notify manager

---

## M4 — Manager Dashboard (Steps 8–12)

**Manager nav:** Assigned Scans, Team Scans, Planogram vs Actual, Corrective Actions

### Planogram vs Actual report
Table columns: Product | Expected | Actual | Status | Issue

Overall: `Planogram Compliance: {compliance_percent}%`

### Corrective Actions
- List from `corrective_actions` joined to comparison lines
- Status dropdown: Open → In Progress → Resolved
- Junior can update on own scans; manager sees all

### Team Scans
Filter `shelf_scans` where `assignment_id is not null`; show assignee, compliance %, issue counts

### On junior submit
Notify manager via `notifications` + optional email Edge Function

---

## Roles

`organization_members.role`:
- Manager UI: `owner`, `admin`, `manager`
- Junior UI: `member`

Invite flow: set `role=member` for reportees.

---

## Sample test CSV

See `data/fixtures/planogram_shampoo_row.csv` in backend repo (8 shampoo bottles, A-1-Z).
