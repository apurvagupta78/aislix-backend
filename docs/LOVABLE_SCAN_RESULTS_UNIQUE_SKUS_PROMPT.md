# Lovable Prompt — Fix Unique SKUs metric on scan results

Paste into Lovable chat, then **Publish**.

**Bug:** Scan `59dd118f-98ac-4341-ad5b-79ec57dc9473` (Lay's + planogram) shows **Unique SKUs: 1** on the results dashboard, but the backend returns **3–4 distinct SKUs** with different `variant` values (Magic Masala, Tomato Tango, Cream & Onion).

Verified on Railway `GET /scan/59dd118f-98ac-4341-ad5b-79ec57dc9473`:
- `metrics.unique_skus`: **4** (correct — one row per detection group)
- `inventory[]`: 4 rows, same `product_name` "Potato Chips", different `variant`
- Planogram table correctly shows 3 flavors with `(variant)` in actual product column

Root cause: UI likely dedupes by `product_name` or `brand` only and ignores `variant`.

---

```
SCAN RESULTS — fix Unique SKUs tile + inventory table variant column

══════════════════════════════════════════════════════════════
UNIQUE SKUS METRIC TILE
══════════════════════════════════════════════════════════════

Do NOT compute unique SKUs from product_name alone.

Preferred (use backend value when present):
```typescript
const uniqueSkus =
  result.metrics?.unique_skus ??
  countUniqueSkus(result.inventory ?? []);
```

If computing client-side, dedupe by brand + product_name + variant (or sku):

```typescript
function inventorySkuKey(row: {
  brand?: string;
  product_name?: string;
  variant?: string;
  sku?: string;
  counted_in_totals?: boolean;
}): string {
  if (row.counted_in_totals === false) return ""; // exclude from SKU count
  const sku = (row.sku || "").trim().toLowerCase();
  if (sku) return sku;
  const brand = (row.brand || "unknown").trim().toLowerCase();
  const product = (row.product_name || row.name || "unknown").trim().toLowerCase();
  const variant = (row.variant || "").trim().toLowerCase();
  return `${brand}|${product}|${variant}`;
}

function countUniqueSkus(inventory: InventoryRow[]): number {
  const keys = new Set<string>();
  for (const row of inventory ?? []) {
    const key = inventorySkuKey(row);
    if (key) keys.add(key);
  }
  return keys.size;
}
```

WRONG (causes "1 SKU" for Lay's rack):
```typescript
// ❌ collapses all Lay's flavors
new Set(inventory.map(r => r.product_name)).size

// ❌ same problem
new Set(inventory.map(r => `${r.brand}-${r.product_name}`)).size
```

RIGHT:
```typescript
// ✅ includes variant
countUniqueSkus(inventory)  // → 3 or 4 for Lay's scan
```

Display tile label unchanged: **Unique SKUs**
Subtext optional: "Distinct brand + product + variant"

══════════════════════════════════════════════════════════════
PRODUCTS / INVENTORY TABLE (if shown on results)
══════════════════════════════════════════════════════════════

When `variant` is non-empty and not already contained in `product_name`, show:

```typescript
function displayProductName(row: InventoryRow): string {
  const name = row.product_name || row.name || "Unknown";
  const variant = (row.variant || "").trim();
  if (!variant) return name;
  if (name.toLowerCase().includes(variant.toLowerCase())) return name;
  return `${name} (${variant})`;
}
```

This matches planogram compliance table format:
  `Potato Chips (Magic Masala)`

Add **Variant** column to inventory table when any row has variant — or use displayProductName in Product column.

══════════════════════════════════════════════════════════════
PRODUCTS DETECTED vs UNIQUE SKUS
══════════════════════════════════════════════════════════════

Keep existing semantics:
- **Products Detected** = `metrics.total_products` (sum of quantities / facings)
- **Unique SKUs** = `metrics.unique_skus` OR countUniqueSkus(inventory)

Do not set both to the same dedupe logic.

══════════════════════════════════════════════════════════════
PERSIST ON SCAN COMPLETE
══════════════════════════════════════════════════════════════

When saving to shelf_scans, persist full metrics object including unique_skus:

```typescript
await supabase.from("shelf_scans").update({
  metrics: result.metrics,
  // metrics.unique_skus must survive — do not overwrite with client recalc using product_name only
}).eq("id", scanId);
```

If results page reads from shelf_scans.metrics, use metrics.unique_skus from DB — not a recomputed wrong value.

══════════════════════════════════════════════════════════════
QA
══════════════════════════════════════════════════════════════

After fix, rescan or reload scan `59dd118f-98ac-4341-ad5b-79ec57dc9473`:
- Unique SKUs tile shows **3** or **4** (not 1)
- Planogram table still shows 3 expected flavors with variant in actual column
- Products Detected stays ~47 (total facings)

Test non-chips category (e.g. toothpaste with 5 variants): Unique SKUs must count variants separately.

No backend changes required.
```
