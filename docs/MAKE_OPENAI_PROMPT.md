# Make.com OpenAI — Final Prompt (copy/paste)

**Make wiring:** User message → paste block below. Text prompt: `{{11.metadata}}`. Image: `11.image:data` + `11.image:name` (webhook module **11**, not 1).

**Settings:** Response format = JSON Object | Temperature = **0.3** | Max tokens = **8192** | Image detail = **High**

**Model: gpt-5.6-sol (reasoning)** — sol may emit prose or markdown before JSON. Backend now strips that automatically, but in Make you MUST still set:
- **Response format → JSON Object** (not Text)
- **Max output tokens → 8192+** (reasoning uses tokens before JSON; 4096 can truncate large shelves)
- **Webhook response body** → pass the OpenAI module output through unchanged (do not wrap in extra quotes)

If scans still fail, open Make execution history → last OpenAI module → check whether `content` is empty (increase max tokens) or non-JSON (enable JSON Object mode).

---

## Make.com module wiring (CRITICAL — fixes "Accepted" / invalid JSON errors)

Your scenario order:
1. **Webhooks → Custom webhook** (trigger)
2. **OpenAI → Create a Chat Completion** (vision + JSON)
3. **Google Sheets → Add a Row** (optional logging)
4. **Webhooks → Webhook response** (MUST return scan JSON to Aislix)

### OpenAI module (module 2 in your screenshot)

| Setting | Value |
|---------|--------|
| Model | gpt-5.6-sol |
| Response format | **JSON Object** |
| **Parse JSON Response** | **Yes** ← your screenshot shows **No** — change this |
| Max Output Tokens | **8192** (not 4096) |
| Image detail | High |
| Temperature | 0.3 (ignored on gpt-5.6 — OK) |

User message: metadata line + prompt block below.  
Image: `{{1.image:data}}` + `{{1.image:name}}` (adjust `1` to your webhook module number).

### Webhook response module (LAST module — this is the bug)

**Problem today:** Aislix receives plain text `Accepted` instead of scan JSON. That means the Webhook response module is using Make's default body, not the OpenAI output.

**Fix:**

1. Open **Webhooks → Webhook response** (last module)
2. **Status:** `200`
3. **Body:** map the **OpenAI module output** — try in this order:
   - `{{2}}` (entire OpenAI module output as JSON) — if OpenAI is module 2
   - OR `{{2.result}}` when Parse JSON Response = Yes
   - OR `{{2.choices[0].message.content}}` when Parse JSON Response = No
4. **Content-Type header:** `application/json`
5. **Do NOT** leave body empty or as default "Accepted"

**Verify:** Run scenario once → Webhook response module output in history must contain `"products": [...]` — not the word `Accepted`.

### Still getting `Accepted` after Body = `13.Result`?

`Accepted` is Make's **default instant ack** — it means Aislix never received your Webhook response body. Check in order:

1. **Remove the JSON Parse module** between OpenAI and Webhook response.  
   With **Parse JSON Response = Yes** on OpenAI, `13.Result` is already an object. A JSON Parse module often **errors** (expects a string) and the flow **never reaches** module 24.  
   **Correct chain:** `Webhook (11) → OpenAI (13) → Webhook response (24)` — nothing in between.

2. **Run once** in Make → every module must be **green**, especially module 24.  
   If OpenAI or JSON Parse is **red**, fix that first — Webhook response never runs.

3. **Scenario must be ON** (toggle bottom-left) and **Saved** after every edit.

4. **Webhook URL must match Railway** — copy URL from module **11 (Custom webhook)** and confirm it equals `MAKE_SCAN_WEBHOOK_URL` in Railway env. Aislix may still be calling an **old scenario URL**.

5. **Open module 24 execution output** — must show `{ "products": [...] }`. If module 24 never appears in history, the scenario stops earlier.

6. **Webhook response Body** — use `13.Result` only (one chip). Do not also map `Choices[].Message.Content`.

7. **Timeout** — sol + Extremely high reasoning can exceed Make's webhook wait. Try Reasoning effort **Medium** and re-test.

### Error: `Make.com response did not include inventory or facings`

JSON is reaching Aislix, but there is no usable `products[]` (or `inventory` / `facings`) list.

**Check in Make execution history (module 13 → module 24):**

1. **Module 13 (OpenAI) output** — must contain `"products": [ {...}, ... ]` with at least one row.  
   If `products` is missing or `[]`, the model did not finish the audit (token limit, timeout, or reasoning-only output). Fix: **Reasoning effort → Medium**, **Max output tokens → 8192+**, re-run once.

2. **Module 24 (Webhook response) Body** — must pass the OpenAI JSON through:
   - Best: `{{13.Result}}` when **Parse JSON Response = Yes**
   - Or explicit body:
     ```json
     {
       "products": {{13.products}},
       "executive_summary": {{13.executive_summary}}
     }
     ```
   - Avoid mapping the whole module bundle if it wraps fields under `Result` without exposing `products`.

3. **Do not put JSON Parse between OpenAI and Webhook response** — it often errors and module 24 never runs.

4. After a successful run, module 24 output in history must look like:
   ```json
   { "products": [ { "brand": "...", "product": "...", "qty": 3 } ], "executive_summary": "..." }
   ```

The backend now unwraps `Result`, `items`, and `detected_products` aliases; if the error persists, the OpenAI step is returning empty or malformed product data — fix module 13 first.

### GPT says `no shelf image was provided` (products: [])

OpenAI module output looks like:

```json
{
  "products": [],
  "executive_summary": "Visual audit could not be completed because no shelf image was provided..."
}
```

**This is not a Webhook response bug.** The text prompt/metadata reached GPT, but the **vision image attachment is missing** in module 13.

**Fix — OpenAI module 13:**

1. Open **OpenAI → Generate a completion** (module 13).
2. Under **Messages** (User role), you need **two parts** — not text only:
   - **Text** — your audit prompt + `{{11.metadata}}`
   - **Image** — map from the webhook file:
     - **Image data / file:** `{{11.image:data}}` (or pick **Webhooks → 11 → image → data** in the mapper)
     - **Image name** (if asked): `{{11.image:name}}`
3. Set **Image detail → High**.
4. Save scenario → run a real scan from aislix.com (not empty “Run once” without webhook data).

**Verify before re-testing Aislix:**

| Module | What to check in execution history |
|--------|-------------------------------------|
| **11 Webhook (input)** | Bundle includes **`image`** with file name + size (not empty) |
| **13 OpenAI (input)** | Request includes an **image** part alongside text — not metadata text only |
| **13 OpenAI (output)** | `products` array has rows with brand/product/qty |

**If webhook 11 has no `image` file:**

- Railway `MAKE_UPLOAD_MODE` must be **`multipart`** (default). Aislix sends field name **`image`**.
- Webhook URL in Railway `MAKE_SCAN_WEBHOOK_URL` must match module **11** URL exactly.

**If webhook 11 has `image` but OpenAI input has no image:**

- Re-add the **Image** content block in module 13 and map `{{11.image:data}}` again (most common fix).

**If you only see Role + Text (no Image option) in Generate a completion:**

Make does **not** use a separate “Image message type” in this module. Image fields appear **inside the same User message**, **below** the text box — but only for vision-capable models.

1. **Delete** extra empty User messages (e.g. Message 3 with blank text).
2. Use **one User message** (Message 2) for the full audit prompt + `{{11.metadata}}`.
3. **Scroll down inside that same message block** (below Text Content). With **Show advanced settings = ON** and model **gpt-5.6-sol** / **gpt-4o**, you should see:
   - **Image input type** → File / Binary
   - **Image file data** → `{{11.image:data}}`
   - **Image detail** → High
4. If those fields still do not appear, **change model** temporarily to **gpt-4o** — save — reopen the message and check again (some Make versions only show image fields for certain models).

**Easier alternative — use “Analyze images (Vision)” instead of “Generate a completion”:**

If image fields never appear in Generate a completion:

1. Delete OpenAI module 13.
2. Add **OpenAI → Analyze images (Vision)**.
3. **Prompt** → paste the full audit prompt + `{{11.metadata}}`.
4. **Images → Add** → **Image file** → map `{{11.image:data}}`.
5. **Model** → gpt-5.6-sol (or gpt-4o).
6. **Max tokens** → 8192.
7. Webhook response 24 Body → map the vision module text output (e.g. `{{13.text}}` or full module output). Backend parses JSON from the text response.

Chain becomes: `Webhook 11 → Analyze images (Vision) 13 → Webhook response 24`.

**JSON mode only** (`MAKE_UPLOAD_MODE=json` on Railway): webhook receives `image_base64` + `image_mime`, not `image:data`. You must map base64 into the OpenAI image field (or switch Railway back to `multipart`).

### Google Sheets module

Can stay between OpenAI and Webhook response. Do not let Sheets be the last module — Aislix never receives Sheets output.

---

Copy everything inside the code fence below into your Make.com OpenAI module user message (after the metadata line).

```
Act as a professional retail shelf auditor. Perform a complete visual audit before returning JSON.

Treat this like a human auditor: identify every UNIQUE visible product, count front-facing units accurately, then output one JSON object.

=========================
AUDIT CONTEXT (COMPLIANCE — NOT A DETECTION FILTER)
=========================

Audit context from webhook (JSON):
{{11.metadata}}

The audit sub-category (e.g. toothpaste, chips, beverages) defines compliance scope.
It does NOT limit detection.

You MUST detect and return EVERY visible retail product, including:
- Products matching the audit sub-category
- Misplaced products (water, mouthwash, dishwash, snacks on a toothpaste shelf, etc.)
- Partially visible or edge-cropped products with visible evidence

For EVERY product row set product_category to the TRUE category:
toothpaste | mouthwash | water | dishwash | chips | soda | iced tea | soap | shampoo | unknown | etc.

Do NOT omit mismatched categories. Do NOT filter to audit sub-category only.

=========================
BRAND ACCURACY (READ PACKAGING — NO GUESSING)
=========================

When shelf_brand_guide is in metadata, follow it exactly.

General rules:
- Set brand ONLY from readable logo/text on the package — never from box color alone.
- Red toothpaste packaging is often Odol, Closeup, or Colgate — NOT Dabur Red unless "DABUR" is visible.
- "Doctor" is a real regional toothpaste brand — never label it as Dabur.
- "Dento" is NOT a brand — it is usually a misread of Doctor.
- Do NOT default to India-market brands (Dabur, Pepsodent, Himalaya) on international shelves.
- If brand text is unreadable, use "Unknown" — do not invent a familiar brand.

=========================
PLANOGRAM (WHEN planogram_expected_skus IS IN METADATA)
=========================

Return exactly ONE products[] row per expected SKU with:
- Matching brand, product, variant (flavor)
- qty = YOUR visual count for THAT SKU only

planogram expected_qty is for downstream compliance comparison ONLY.
NEVER copy expected_qty into your qty field.

Do NOT merge different flavors into one row.

FORBIDDEN:
- One row: Lay's / Potato Chips / qty 56
- One row: Colgate / Toothpaste / qty 40
- Tomato Tango qty 12 when only ~6 red front facings visible in one row

CORRECT (Lay's example):
- Lay's / Potato Chips / Magic Masala / qty = sum of blue rows
- Lay's / Potato Chips / Tomato Tango / qty = red row front facings only
- Lay's / Potato Chips / American Style Cream and Onion / qty = sum of green rows

Lay's color map (mandatory):
- Blue bags → Magic Masala (or India's Magic Masala)
- Red bags → Tomato Tango (or Spanish Tomato Tango)
- Green bags → American Style Cream and Onion

Put flavor in variant when product is generic (e.g. "Potato Chips").

=========================
QTY COUNTING — ROW BY ROW (CRITICAL)
=========================

For vertical racks and multi-row shelves:

1. Identify each horizontal shelf row (visual band separated by shelf edge or color change).
2. For EACH row separately: read variant from packaging color/text — never assume all rows are the same SKU.
3. Count LEFT → RIGHT: each visible FRONT-FACING bag/box/bottle = 1.
4. Default rule: count ONLY the front face visible to the camera.
5. Do NOT multiply by 2 or 3 for "shelf depth" unless a second distinct front face is clearly visible behind the first.
6. Sum row counts per unique brand + product + variant → ONE products[] row per SKU.

Lay's 6-row rack example (typical):
- Rows 1–3 blue (Magic Masala): if each row has 6 front bags → 6+6+6 = 18 (NOT 36, NOT 12 for one row labeled Tomato)
- Row 4 red (Tomato Tango): if 6 red front bags → qty = 6 (NOT 12)
- Rows 5 AND 6 green (Cream & Onion): BOTH rows must be summed — if 6+6 → qty = 12 (NOT 6 from only one green row)

LAY'S MANDATORY PRE-JSON CHECK:
Before returning JSON, mentally write:
  Blue row1: _6_  row2: _6_  row3: _6_  → Magic qty = _18_
  Red row4: _6_  → Tomato qty = _6_
  Green row5: _6_  row6: _6_  → Cream qty = _12_
If Tomato qty equals 2× visible red front facings, you double-counted — fix it.
If any qty differs from planogram expected_qty by >2, recount that color row once.

FORBIDDEN qty patterns:
- Using planogram expected_qty as qty
- Doubling a single row count (6 visible → qty 12)
- Merging all chip rows into one Potato Chips total
- Two products[] rows for the same flavor
- Assigning Tomato qty to blue rows or Cream qty to red rows

=========================
FRONT-FACING COUNT (ALL CATEGORIES)
=========================

Default for toothpaste, chips, shampoo, water, soda:
- One visible front face = qty 1 at that position
- Count visible front units left-to-right, row-by-row
- If uncertain between N and 2N, choose N unless a second front face is clearly visible

Toothpaste: count visible front boxes/cartons only.
Water bottles / soda bottles: count visible bottle fronts left-to-right.
Do NOT estimate hidden stock behind the shelf.

=========================
VARIANT NAMING (USE CONSISTENT LABELS)
=========================

Use SHORT, consistent variant strings so the same SKU never appears twice with different labels.

Pack size labels (pick ONE style per SKU):
- 2 L bottle → variant: "2 L" (NOT "Regular, 2 L" or "2 L bottle")
- Single bottle → variant: "Single-serve bottle"
- Can multipack → variant: "12-pack cans" or "24-pack cans"
- Diet vs Regular → always prefix: "Diet, 2 L" vs "Original, 2 L"

Flavor / line extensions go in variant:
- "Ginger Ale and Lemonade, 2 L"
- "Ginger Ale and Orangeade, 12-pack cans"

Same physical SKU seen in multiple shelf zones → ONE row, summed qty, one variant string.

=========================
GROUPING & DEDUPLICATION (CRITICAL)
=========================

After counting across the ENTIRE image:

- ONE products[] row per unique brand + product + variant + product_category
- Sum qty across ALL shelf positions (Top Left + Bottom Right + etc.) for that SKU
- NEVER create two rows for the same brand + product + variant just because shelf_position differs
- shelf_position on each row = where the MAJORITY of that SKU's facings appear (pick one)

Different pack size = different row (correct):
- 2 L vs 12-pack cans vs single-serve bottle = 3 rows for same brand/product

Different flavor/line = different row (correct):
- Diet vs Original, Lemonade vs Orangeade = separate rows

BEVERAGE SHELVES:
- Canada Dry / Ginger Ale with 10 different pack formats = up to 10 rows (correct)
- Canada Dry / Ginger Ale / "2 L" must appear ONLY ONCE with total qty summed across the shelf

Before returning JSON, scan products[] for duplicate brand+product+variant keys and merge them.

Sum of all qty values = total unique front-facing units you counted.

=========================
WORKFLOW
=========================

1. Scan entire image: TOP → BOTTOM, LEFT → RIGHT.
2. Detect every unique visible product / SKU group.
3. Count front facings per row, then sum per SKU.
4. Merge duplicate SKU rows (same brand + product + variant).
5. Reconcile counts before JSON.
6. Return JSON only after full image scan is complete.

Do NOT estimate. Do NOT guess completely hidden products.
Accuracy is more important than speed.

=========================
OUTPUT FORMAT
=========================

Return ONLY valid JSON.
No markdown. No ```json. No text outside JSON.

{
  "products": [
    {
      "brand": "",
      "product": "",
      "variant": "",
      "qty": 0,
      "confidence": 0.0,
      "shelf_position": "Top Left Front",
      "product_category": "soda",
      "bbox_2d": [0, 0, 0, 0]
    }
  ],
  "executive_summary": "One short paragraph: shelf health, key brands, planogram gaps, misplaced products, and competitive shelf-share context (which brands lead facings vs rivals on this bay).",
  "role_summaries": {
    "execution": "2-3 sentences for field reps: what to fix now, top OOS/placement issues, rescan guidance.",
    "merchandising": "2-3 sentences for category managers: planogram gaps, facing compliance, category mix.",
    "brand": "2-3 sentences for brand managers: own brand share vs competitors, priority SKU availability.",
    "executive": "2-3 sentences for business leaders: execution score context, top risks, where to intervene."
  },
  "recommended_actions": [
    {
      "action_id": "replenish-sku-1",
      "issue_type": "oos",
      "priority": "high",
      "title": "Replenish SKU name",
      "reason": "Why this matters — reference detected evidence only",
      "recommended_action": "Specific fix (replenish, move, replace)",
      "expected_state": "4 facings",
      "actual_state": "0 facings"
    }
  ],
  "competitive_insights": [
    {
      "brand": "Leading competitor brand on shelf",
      "share_note": "Approximate facing share vs your focus brand if metadata includes brand focus",
      "action": "One merchandising action to close the gap"
    }
  ],
  "retail_intelligence": {
    "ai_confidence": { "value": 0.85, "state": "calculated" },
    "recognition_coverage": { "value": 0.91, "state": "calculated" },
    "image_quality": { "overall_state": "available", "rescan_recommended": false },
    "planogram_analysis": { "status": "not_configured" }
  }
}

Field rules:
- brand: never empty ("Unknown" if unreadable)
- product: never empty (e.g. "Ginger Ale", "Orange Soda", "Root Beer")
- variant: pack size / flavor / diet flag — REQUIRED; use consistent labels from VARIANT NAMING section
- qty: integer, front-facing visual count only (summed across entire shelf for that SKU)
- confidence: SKU identification confidence (0.80–0.99, never 1.00)
- shelf_position: one of Top/Middle/Bottom + Left/Right + Front/Back (9-grid) — primary location only
- product_category: true category for compliance
- bbox_2d: [x1,y1,x2,y2] normalized 0–1000, tight around that SKU's visible block

=========================
CONFIDENCE
=========================

0.99 = fully visible pack
0.95 = mostly visible
0.90 = partially visible
0.80 = small portion but identifiable
Confidence reflects identification, NOT counting certainty.

=========================
BBOX_2D (RETURN FOR EACH products[] ROW)
=========================

Coordinates 0–1000: x1,y1 top-left; x2,y2 bottom-right.
One bbox per products[] row, tight around that SKU's visible region on shelf.

Rules:
- Box must overlap visible packaging (not empty ceiling/wall)
- One variant per box — do not span whole shelf with one box
- Lay's: 3 SKUs → 3 boxes (blue block, red row, green block)
- Toothpaste: separate box per variant block at its shelf height
- Beverages: one box per pack-format block (e.g. all 2L Canada Dry in one band)
- Area ≤ 45% of image; y1 usually ≥ 100 unless products start at top edge

=========================
FINAL CHECKLIST (ALL MUST PASS)
=========================

1. Every visible product category included (not filtered to audit only)
2. One row per unique SKU (no merged flavors, no merged pack sizes)
3. No duplicate rows for same brand + product + variant (merged qty)
4. qty = visual front-facing count only (NOT planogram expected_qty)
5. Lay's: blue/red/green rows mapped to correct variants
6. Lay's: Tomato qty = red row front count (typically 6, not 12)
7. Lay's: Magic qty = sum of blue row front counts only
8. Every row has product_category, variant (when readable), bbox_2d
9. Variant strings follow VARIANT NAMING rules (no "Regular, 2 L" AND "2 L" for same SKU)
10. If planogram_expected_skus present: len(products[]) matches expected SKU count
11. executive_summary mentions planogram qty gaps if any
12. executive_summary names top 2–3 brands by facing count and notes competitive gaps (who leads shelf share on this bay)
13. competitive_insights: 1–3 rows when multiple brands visible — flag rivals with more facings than the audit brand
14. role_summaries: distinct copy per view (execution / merchandising / brand / executive) — never generic marketing fluff
15. recommended_actions: prioritized fixes tied to evidence; never invent prices, sales, or planogram scores
16. retail_intelligence.planogram_analysis.status = "not_configured" when no planogram in metadata — do NOT fabricate compliance

You are Aislix Retail Intelligence Engine. Convert visual retail evidence into structured, explainable, actionable retail execution intelligence. Never invent information — only claims supported by the image, catalogue, planogram, or supplied metadata.

Return ONLY valid JSON.
```
