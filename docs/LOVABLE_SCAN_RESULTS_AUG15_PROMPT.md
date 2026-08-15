# Lovable Prompt — Scan results (annotated image + planogram compliance)

Paste into Lovable chat, then **Publish**. Backend commit `fb02415`+ is live on Railway.

---

```
Fix scan results page — annotated shelf image + planogram compliance display.

## A) Annotated shelf image (fix blue/blur + truncated labels)

### Problem
Scan result page shows a blurred/blue-tinted shelf image with broken labels ("Lays -" only).
Backend sends a clean JPEG with flavor labels. Frontend is re-drawing on canvas or re-encoding.

### Fix — use backend image bytes directly

```tsx
const raw = scanResult?.raw_payload ?? scanResult;
const annotatedSrc =
  downloads?.annotated_image_url ??
  (raw?.annotated_image_base64
    ? `data:image/jpeg;base64,${raw.annotated_image_base64}`
    : raw?.original_image_base64
      ? `data:image/jpeg;base64,${raw.original_image_base64}`
      : null);

{annotatedSrc && (
  <img
    src={annotatedSrc}
    alt="Annotated shelf"
    className="w-full rounded-lg"
    style={{ objectFit: "contain", maxHeight: "70vh" }}
  />
)}
```

**Remove:**
- Canvas/SVG overlays that re-draw boxes from `products[]` or `inventory[]`
- CSS `filter: blur()` or blue tint layers
- `object-fit: cover` on shelf photos (use `contain`)

**When saving to Supabase `scan_images` (kind=`annotated`):**
Store the exact `annotated_image_base64` JPEG from Railway — no client-side re-encode, crop, or resize.

**Downloads:** use blob download (see `docs/scan-downloads.ts`), not `window.open`.

---

## B) Planogram compliance tile + detail section

Backend now returns:
- `metrics.planogram_compliance_percent` — **SKU presence** (3/3 found = 100%)
- `metrics.planogram_qty_compliance_percent` — **quantity accuracy** (may be lower)
- `metrics.planogram_sku_match_percent` — same as headline SKU %
- `planogram_compliance.lines[]` — expected vs actual table
- `planogram_compliance.corrective_actions[]`

### Metric tile (with planogram scans only)

```
Planogram compliance: {planogram_compliance_percent}%
Subtext: {planogram_sku_match_percent}% SKU match · qty accuracy {planogram_qty_compliance_percent}%
```

When all 3 SKUs found but qty wrong (e.g. scan 95c2177b):
- Show **100%** headline (SKU match) — NOT 0%
- Show qty issues in detail table + corrective actions

### Detail section (below tiles)

Show when `planogram_compliance` is non-null (Option 2 ad-hoc OR assigned scan):

**Summary mini-tiles:** Expected | Found | Missing | Qty issues | Wrong product | Wrong category

**Table** from `planogram_compliance.lines`:
| Expected product | Expected qty | Actual qty | Status | Issue |

**Corrective actions** from `planogram_compliance.corrective_actions`

Persist on scan complete:
```typescript
await supabase.from("shelf_scans").update({
  planogram_compliance_percent: result.metrics?.planogram_compliance_percent,
  metrics: result.metrics,
  planogram_compliance: result.planogram_compliance,
}).eq("id", scanId);
```

---

## C) Persist new image fields

When scan completes, store in `raw_payload` or metrics:
- `annotated_image_base64`, `annotated_image_width`, `annotated_image_height`
- `original_image_base64`, `original_image_width`, `original_image_height`

---

## TEST

1. Re-scan Lay's A-1-L **with planogram** → tile shows 100% SKU match, qty issues in table
2. Re-scan **without planogram** → 3 SKUs in inventory (not 2)
3. Annotated image matches PDF — clean colors, labels like "Magic Masala" / "Tomato Tango" / "Cream & Onion"
4. Download annotated image → saves as JPG, not new tab

Do not change Railway backend in Lovable.
```
