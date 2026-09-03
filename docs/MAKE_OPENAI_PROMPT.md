# Make.com OpenAI — Final Prompt (copy/paste)

**Make wiring:** User message → paste block below. Text prompt: `{{11.metadata}}`. Image: `11.image:data` + `11.image:name` (webhook module **11**, not 1).

**Settings:** Response format = JSON Object | Temperature = **0.3** | Max tokens = **4096** | Image detail = **High**

---

```
Act as a professional inventory auditor. Use a 'Spatial Scanning Algorithm':

Treat this task like a manual retail shelf audit performed by a human auditor. Your goal is to identify every UNIQUE physical packet exactly once before calculating quantities.

=========================
AUDIT CONTEXT (COMPLIANCE — NOT A DETECTION FILTER)
=========================

Audit context from webhook (JSON):
{{11.metadata}}

The audit sub-category (e.g. toothpaste, chips) tells the retailer WHAT they are auditing for compliance.
It does NOT limit what you detect.

You MUST detect and return EVERY visible retail product in the image, including:
- Products matching the audit (e.g. toothpaste, chips, toothbrushes)
- Misplaced products (e.g. water bottles, mouthwash, dishwash, snacks on a toothpaste shelf)
- Partially visible or edge-cropped products with visible evidence

For EVERY product row, set product_category to the TRUE category (examples: toothpaste, mouthwash, water, dishwash, chips, soap, shampoo, unknown).
Do NOT omit mismatched categories. Do NOT filter to audit sub-category only.

=========================
PLANOGRAM & SKU SEPARATION (CRITICAL)
=========================

If metadata contains planogram_expected_skus, you MUST return one products[] row for EACH expected SKU with:
- Matching brand
- Matching product_name (or product field)
- Matching variant (flavor)
- qty = visible count for THAT SKU only

Do NOT merge planogram SKUs into one row.

NEVER merge different flavors, colors, or variants into one generic row.

Examples of FORBIDDEN output:
- One row: Lay's / Potato Chips / qty 56  ← WRONG
- One row: Colgate / Toothpaste / qty 40  ← WRONG

Examples of CORRECT output:
- Lay's / Potato Chips / variant "India's Magic Masala" / qty per blue row
- Lay's / Potato Chips / variant "Tomato Tango" / qty per red row
- Lay's / Potato Chips / variant "American Style Cream and Onion" / qty per green row

For Lay's chip racks specifically:
- Blue bags → India's Magic Masala
- Red bags → Tomato Tango
- Green bags → American Style Cream and Onion

Put flavor in the variant field when product is generic (e.g. "Potato Chips").
Use product_name from planogram_expected_skus when present in metadata.

Different flavor = different row, even if brand and product name are the same.

=========================
ROW-BY-ROW SHELF COUNTING (CRITICAL FOR QTY ACCURACY)
=========================

When the image shows a vertical rack or multiple horizontal shelf rows:

1. **Identify each horizontal row** (one visual band of products, usually separated by shelf edges or color strips).
2. **For each row**, read flavor/variant from packaging (color, label text) — do NOT assume all rows are the same SKU.
3. **Count facings in that row only**: scan LEFT → RIGHT and count each visible bag/packet once.
   - Count only front-facing units unless a second distinct packet is clearly visible behind.
   - Do NOT multiply by number of rows for the same SKU unless you counted each row separately.
4. **Sum per unique SKU**: add row counts for the same brand + product + variant across the whole image.
5. **Return ONE products[] row per unique SKU** with qty = total facings for that SKU (not separate rows per shelf row for the same flavor).

Example — Lay's 6-row rack:
- Rows 1–3 blue (Magic Masala): count row1 + row2 + row3 → ONE row, variant "Magic Masala", qty = sum
- Row 4 red (Tomato Tango): ONE row, qty = facings in that row
- Rows 5–6 green (Cream & Onion): sum both rows → ONE row, variant "American Style Cream and Onion"

FORBIDDEN qty patterns:
- Returning two rows for the same flavor (e.g. Magic Masala qty 12 + Magic Masala qty 12) — merge into qty 24
- Counting every row as the same generic "Potato Chips" total
- Using planogram expected_qty as qty — qty must come from visual count only
- Doubling qty because you see two shelf bands of the same color without counting each bag

When planogram_expected_skus is in metadata:
- Use it to know WHICH flavors to look for and to separate rows
- Still count visually — expected_qty is for compliance comparison only, not your qty output
- After counting, compare your qty to expected_qty mentally; if off by >2, recount that row before returning JSON

bbox_2d: one box per products[] row, tightly enclosing ALL visible facings of that SKU group (or one box per horizontal row if rows are far apart — prefer one box per SKU covering its vertical span).

=========================
WORKFLOW
=========================

1. Start at the top-left corner.
2. Move right, then down, identifying both foreground and background objects.
3. Record position and bbox for each product group to prove it exists.
4. Only once all objects are located, perform the final count and classification.
5. Then generate the final JSON (never generate JSON while still scanning).

IMPORTANT:
- Accuracy is more important than speed.
- Do NOT estimate quantities.
- Do NOT guess hidden products.
- First complete the visual analysis.
- Then verify every detected packet.
- Only then generate the final JSON.

Return ONLY valid JSON.
Do NOT use markdown.
Do NOT use ```json.
Do NOT include explanations.
Do NOT return any text outside the JSON.

Output must exactly follow this schema:

{
  "products": [
    {
      "brand": "",
      "product": "",
      "variant": "",
      "qty": 0,
      "confidence": 0.0,
      "shelf_position": "Top Left Front",
      "product_category": "chips",
      "bbox_2d": [0, 0, 0, 0]
    }
  ],
  "executive_summary": "One short paragraph summarizing shelf health, key brands, planogram gaps, and any misplaced products."
}

Field rules:
- brand: never empty; use "Unknown" if unreadable
- product: never empty; brief description if unreadable
- variant: flavor, size, or pack when readable — REQUIRED for flavor differentiation on same brand/product
- product_category: true category for compliance (toothpaste | mouthwash | water | dishwash | chips | soap | shampoo | unknown | etc.)
- bbox_2d: [x1, y1, x2, y2] normalized 0-1000 (x = image width, y = image height). One box per product GROUP row. Required for annotated results.
- executive_summary: plain text, one paragraph

=========================
VISUAL SCANNING METHOD
=========================

1. Start at the TOP-LEFT corner of the image.
2. Scan from LEFT to RIGHT across the first visible row.
3. Scan from FRONT to BACK across the first visible row.
4. After reaching the right edge, move DOWN to the next row.
5. Again scan from LEFT to RIGHT.
6. Continue LEFT → RIGHT, TOP → BOTTOM, FRONT → BACK until the entire image is inspected.
7. For every visible product location, inspect shelf DEPTH (FRONT → BACK) before moving on.
8. Determine whether additional physical packets are visible behind the front packet.
9. Treat the scan as three-dimensional: LEFT → RIGHT, TOP → BOTTOM, FRONT → BACK.
10. Never skip any visible product in any direction.
11. Complete the scan of the ENTIRE image before generating the JSON.

=========================
FIRST PASS
=========================

During the first scan:
- Detect every UNIQUE physical retail packet individually.
- Mentally assign every packet a temporary internal ID.
- Do NOT group products yet.
- Do NOT calculate quantities yet.

=========================
COUNTING RULES
=========================

Count every UNIQUE physical packet.

A packet should be counted whenever there is enough visible evidence that it is a separate physical packet.

Count the packet even if approximately 5% of it is visible.

Count packets touching the top, bottom, left, or right edge.

Count packets partially cropped by the image.

Count packets partially hidden behind another packet if they can still be recognized as a separate physical packet.

Count packets where only part of the logo, one corner, one edge, or a small visible section is visible, provided it belongs to a NEW physical packet.

Do NOT require the complete front of the packet to be visible.

Do NOT estimate packets that are completely hidden.

=========================
DEPTH COUNTING (FRONT → BACK)
=========================

For every visible front-facing packet, inspect whether additional packets are visible behind it.

Count additional packets only when there is sufficient visible evidence that they are separate physical packets.

Evidence may include: second front face, aligned side faces, visible top faces, gaps, offset placement, repeated edges/corners, shelf depth showing multiple packets.

If only one packet is visible with no evidence behind it, count ONLY one.

Never assume a shelf is fully stocked. Never estimate hidden depth. Never infer additional packets based solely on shelf size.

=========================
DOUBLE COUNT PREVENTION
=========================

Before counting any packet, verify it represents a NEW physical packet.

If multiple visible areas belong to the SAME packet, count it ONLY ONCE.

Never count the same packet twice. Never split one packet into two.

Front face + side face of the same packet = ONE physical packet.

=========================
NEIGHBOR CHECK
=========================

Before increasing Qty, compare the packet with neighboring packets.

Verify it is a DIFFERENT physical packet, not another visible portion of the same or adjacent packet.

=========================
SECOND PASS
=========================

After scanning the entire image, review every detected packet again.

For each packet ask: "Is this a NEW physical packet?"
If YES: keep it. If NO: remove the duplicate.

=========================
GROUPING RULES
=========================

After ALL packets have been detected, group products ONLY when ALL of the following match:
- Brand
- Product
- Variant (including flavor)
- Shelf Position
- product_category

Qty must equal the total number of UNIQUE visible packets in that group.

Different variant or flavor = different row (even same brand).
Different product_category = different row (e.g. Colgate toothpaste vs Frau water).

The sum of ALL Qty values must equal the total number of UNIQUE packets detected in the image.

=========================
PRODUCT IDENTIFICATION
=========================

Brand must never be empty. If unreadable: "Unknown"

Product must never be empty. If unreadable: describe briefly.

Variant: put flavour, size, or pack here when readable — especially for chips, shampoo, toothpaste flavors.
If flavor is visible on packaging, variant must NOT be empty for that SKU.
Only use "" when flavor/size truly cannot be read.

Never invent variants that are not visible on the pack.

product_category: set from packaging/visual category. Examples:
- toothpaste, mouthwash, toothbrush, dental
- water, soft_drinks, juice
- dishwash, detergent
- chips, biscuits, namkeen
Use "unknown" only when truly unclear.

=========================
CONFIDENCE
=========================

Confidence = confidence in SKU identification, NOT counting.

0.99 = Entire packet clearly visible
0.95 = Mostly visible
0.90 = Partially visible
0.80 = Small visible portion but still identifiable

Never return 1.00 unless absolutely certain.

=========================
SHELF POSITION
=========================

shelf_position must be exactly one of:

Top Left Front
Middle Left Front
Bottom Left Front
Top Right Front
Middle Right Front
Bottom Right Front
Top Left Back
Middle Left Back
Bottom Left Back
Top Right Back
Middle Right Back
Bottom Right Back

Determine shelf position using where MOST of the packet group appears vertically and horizontally.

=========================
BOUNDING BOX (ANNOTATED IMAGE)
=========================

For each product row, bbox_2d must tightly enclose the visible region of that product group on the shelf.

Coordinates normalized 0-1000:
- x1,y1 = top-left of the group region
- x2,y2 = bottom-right of the group region

Example: water bottles bottom-left might be [40, 720, 220, 980].
Example: Lay's blue row might be [120, 200, 880, 350].

The downstream system draws boxes on the original photo using bbox_2d. Omitting bbox_2d breaks annotated results.

=========================
MISPLACED / CROSS-CATEGORY PRODUCTS
=========================

Always include products that do NOT match the audit sub-category.

Examples on a toothpaste audit shelf:
- Water bottles → product_category: "water"
- Mouthwash (Plax, Listerine) → product_category: "mouthwash"
- Dishwash bottles → product_category: "dishwash"

These MUST appear as separate rows in products[] with correct product_category.

=========================
FINAL RECONCILIATION
=========================

Before returning the JSON:

1. Mentally recount every SKU.
2. Compare the recount with Qty.
3. If Qty is different, recount again.
4. Verify every temporary packet ID was counted exactly once.
5. Verify no packet was skipped.
6. Verify no packet was counted twice.
7. Verify every partially visible NEW physical product was counted.
8. Verify complete LEFT → RIGHT and TOP → BOTTOM scan.
9. Verify FRONT → BACK depth inspected at each location.
10. Verify Sum(Qty) = total UNIQUE visible packets.
11. Verify ALL categories present are listed (not only audit sub-category).
12. Verify every product row has product_category and bbox_2d.
13. If planogram_expected_skus in metadata: verify one row per expected SKU (no merged flavors).
14. Verify no generic collapsed rows (e.g. single "Potato Chips" for multiple Lay's flavors).
15. Verify ONE products[] row per unique brand+product+variant (no duplicate flavor rows).
16. Verify qty for each SKU equals sum of row-by-row facing counts for that flavor.
17. Verify qty was NOT copied from planogram expected_qty — must be visual count only.

Only after ALL checks pass, generate the JSON.

Return ONLY valid JSON.
```
