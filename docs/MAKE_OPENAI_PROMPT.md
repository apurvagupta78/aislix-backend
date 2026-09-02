# Make.com OpenAI Prompt — detect all products + annotated image

Paste this into your **OpenAI → Messages → User content** in the Shelf Sense AI scenario.
Map the webhook fields: `image` file + `metadata` (or individual form fields).

## How annotated images work

OpenAI Vision **cannot** return a edited photo directly. Instead:

1. **Recommended:** GPT returns **bounding boxes** (`bbox_2d`) per product in JSON.
2. Aislix backend draws boxes + labels on your **original shelf photo** (accurate overlay).
3. **Fallback:** local YOLO draws boxes if GPT omits coordinates (`MAKE_LOCAL_ANNOTATE=true`).

Do **not** use DALL-E to "generate" an annotated shelf — it will not match the real photo.

## Recommended user message

```
You are a retail shelf vision analyst for Aislix.

Audit context (from webhook metadata JSON):
{{metadata}}

Analyze the attached shelf photo and return ONLY valid JSON (no markdown) in this shape:
{
  "products": [
    {
      "brand": "string",
      "product": "string",
      "variant": "string",
      "qty": number,
      "confidence": 0.0-1.0,
      "shelf_position": "Top Left Front | Middle Center | Bottom Right | etc",
      "product_category": "toothpaste | mouthwash | water | dishwash | chips | etc",
      "bbox_2d": [x1, y1, x2, y2]
    }
  ],
  "executive_summary": "one paragraph shelf audit summary"
}

bbox_2d rules:
- One bbox per product row (the visible product group/region).
- Coordinates normalized 0-1000 relative to image width (x) and height (y).
- x1,y1 = top-left corner; x2,y2 = bottom-right corner.
- Example top-left box: [50, 80, 320, 280]

Detection rules:
1. List EVERY visible product — not only the audit sub-category.
2. Include water bottles, mouthwash, snacks, cleaning products, and any misplaced SKU.
3. The user may be auditing "toothpaste" but you must still return beverages and other categories.
4. Set product_category to the true category for compliance (e.g. water bottles → "water").
5. qty = visible unit count for that product group in that shelf position.
6. Be conservative with confidence; use 0.99 only when certain.
```

## Webhook response module

Keep returning **OpenAI Message.Content** (JSON string) from the Webhook response step.

## Optional: pass metadata into OpenAI

In Make, parse `metadata` form field from webhook:
- `sub_category` → toothpaste
- `audit_instructions` → full detection rules (sent automatically by Aislix backend)

Wire `audit_instructions` or full `metadata` into the OpenAI prompt so GPT knows to include mismatches.

## Backend env (Railway)

```
MAKE_LOCAL_ANNOTATE=true   # fallback YOLO boxes if GPT omits bbox_2d
```

## Annotated image priority

1. `annotated_image_base64` in Make response (if you add a custom draw step later)
2. OpenAI `bbox_2d` on each product → Aislix draws on original photo
3. Local YOLO detection boxes (fallback)

After updating the Make prompt, redeploy Railway and re-scan the same shelf.
