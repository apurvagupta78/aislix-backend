# Lovable prompt — Scan results metric tooltips

Paste into Lovable chat, then **Publish**.

---

## Goal

On **Scan results** (`/scans/:id`), add short tooltips so users understand that **Planogram compliance** and **Avg AI confidence** measure different things.

## Copy (use exactly or very close)

1. **Planogram compliance** (card + header if shown)
   - Tooltip: `Share of expected planogram SKUs found on this shelf. Example: 7 of 8 expected → 88%. A missed facing counts as missing even when recognition confidence on other products is high.`

2. **Avg AI confidence** / **Avg Confidence**
   - Tooltip: `Average recognition certainty for detected facings only. Products YOLO never boxed are not included. Low average usually means ambiguous labels or weak OCR — not the same as planogram compliance.`

3. **Products detected**
   - Tooltip: `Number of physical facings detected by the vision model (bounding boxes), before grouping into SKU inventory.`

4. **Low stock**
   - Tooltip: `SKUs with facing count at or below the low-stock threshold (default: 2 facings).`

## UI notes

- Use the same tooltip component/pattern as elsewhere (info icon `ⓘ` on hover, accessible `aria-label`).
- Do not merge compliance % and confidence into one score.
- Optional: if backend returns `planogram_gap_fill: true` in metrics JSON, show a subtle badge: `Gap-fill recovery used` with tooltip `Second-pass detection recovered facings missed on the first YOLO pass.`

## Verify

- Open scan with 88% compliance and ~67% avg confidence — both tooltips read clearly and do not contradict each other.
