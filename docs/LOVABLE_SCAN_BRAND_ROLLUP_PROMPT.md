# Lovable — Scan results brand rollup (optional view)

Paste into Lovable for homepage demo + logged-in scan results.

## Goal

Detailed SKU table stays as-is. Add an optional **"Group by brand"** toggle so users can collapse duplicate brand names (e.g. 10 Canada Dry rows → one brand summary with total units + SKU count).

## Where

- Homepage live demo results panel (`/`, `/retail-intelligence`, `/retail-shelf-intelligence`)
- Logged-in scan results page (same product table component if shared)

## UX

1. Above the results table, add toggle: **View: By SKU | By brand** (default **By SKU**).
2. **By SKU** — current behavior (Brand, Product, Variant, Qty columns).
3. **By brand** — aggregate rows from API `products[]` or inventory:
   - **Brand**
   - **SKUs** (count of unique product+variant rows for that brand)
   - **Total Qty** (sum of quantity for that brand)
   - Optional expand chevron → show underlying SKU rows inline (accordion)

## Aggregation (client-side)

```typescript
function rollupByBrand(products: ScanProduct[]) {
  const map = new Map<string, { brand: string; skuCount: number; totalQty: number; items: ScanProduct[] }>();
  for (const p of products) {
    const brand = p.brand || "Unknown";
    const cur = map.get(brand) ?? { brand, skuCount: 0, totalQty: 0, items: [] };
    cur.items.push(p);
    cur.totalQty += p.quantity ?? p.qty ?? 0;
    cur.skuCount = cur.items.length;
    map.set(brand, cur);
  }
  return [...map.values()].sort((a, b) => b.totalQty - a.totalQty);
}
```

Do NOT change API calls. Rollup is display-only.

## CSV export

When **By brand** is active, export button exports the **currently visible** view (brand rollup or SKU detail). Filename suffix: `-by-brand` vs `-by-sku`.

## Copy

- Toggle label: **Group by brand**
- Brand row subtext: `"12 units · 4 SKUs"` (example)

## QA

- [ ] Beverage shelf: Canada Dry shows once in brand view with summed qty
- [ ] Toggle back to By SKU shows all variant rows
- [ ] Metrics chips (Products detected, Unique SKUs) unchanged — always from API totals
