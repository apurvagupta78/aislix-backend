# Make.com OpenAI Prompt — detect all products + mismatches

Paste this into your **OpenAI → Messages → User content** in the Shelf Sense AI scenario.
Map the webhook fields: `image` file + `metadata` (or individual form fields).

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
      "product_category": "toothpaste | mouthwash | water | dishwash | chips | etc"
    }
  ],
  "executive_summary": "one paragraph shelf audit summary"
}

Rules:
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
MAKE_LOCAL_ANNOTATE=true   # default — draws YOLO boxes on annotated image
```

After updating the Make prompt, redeploy Railway and re-scan the same shelf.
