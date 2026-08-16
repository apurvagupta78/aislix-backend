# Lovable Prompt — Send ALL category selections to POST /scan (multi-rack fix)

Paste into Lovable chat, then **Publish**.

**Status:** Railway backend **already deployed** (`d526f54+`). AI now uses every selection when `category_selections` or `sub_categories` is sent. If the frontend only sends the first tag, mixed shelves (e.g. Shampoo + Soap + Deodorant on A-1-Z) still mis-scope and show false category mismatches.

**Pages:** `/scan`, assign-scan flow, any code path that calls `POST /scan`.

---

```
URGENT FIX — Multi category·subcategory must reach POST /scan

Problem:
- User can pick multiple shelf types (e.g. Personal Care · Shampoo + Soap + Deodorant + Toothpaste)
- UI shows all tags in results header
- But POST /scan only sends legacy single fields: category + sub_category (first tag only)
- Backend AI scopes to ONE sub-category → 20+ false mismatches and wrong identifications on mixed PC shelves

Backend is LIVE and expects (any of these):

1) Preferred — full objects:
   category_selections: [
     {
       category_id: "personal_care",
       category_name: "Personal Care",
       sub_category_id: "shampoo",
       sub_category_label: "Shampoo"
     },
     {
       category_id: "personal_care",
       category_name: "Personal Care",
       sub_category_id: "deodorant",
       sub_category_label: "Deodorant"
     },
     ...
   ]

2) Fallback — same aisle, sub id list:
   category: "Personal Care"          // primary category name
   sub_category: "shampoo"            // primary sub (first tag) — KEEP for backward compat
   sub_category_label: "Shampoo"
   sub_categories: ["shampoo", "soap", "deodorant", "toothpaste", "skincare", "shaving"]

3) Assign-scan scope passthrough:
   assignment_scope_values.category_selections — copy into POST /scan category_selections

══════════════════════════════════════════════════════════════
1. FIND THE POST /scan CALL
══════════════════════════════════════════════════════════════

Search codebase for POST /scan, scan API, startScan, submitScan, etc.

Ensure EVERY scan submission includes category_selections built from the
CategorySubcategoryPicker / shelf-type chips — not just selections[0].

Example payload shape:

{
  "scan_id": "...",
  "store_id": "...",
  "location": "A-1-Z",
  "category": "Personal Care",
  "sub_category": "shampoo",
  "sub_category_label": "Shampoo",
  "category_selections": [
    { "category_id": "personal_care", "category_name": "Personal Care", "sub_category_id": "shampoo", "sub_category_label": "Shampoo" },
    { "category_id": "personal_care", "category_name": "Personal Care", "sub_category_id": "soap", "sub_category_label": "Soap" },
    { "category_id": "personal_care", "category_name": "Personal Care", "sub_category_id": "deodorant", "sub_category_label": "Deodorant" }
  ],
  "sub_categories": ["shampoo", "soap", "deodorant"],
  "image_urls": [...]
}

Rules:
- category_selections.length MUST equal number of shelf-type chips user added
- Legacy category/sub_category/sub_category_label = FIRST chip (primary) — do not remove
- When only ONE chip: category_selections can be omitted OR array of length 1 (both OK)

══════════════════════════════════════════════════════════════
2. SUPABASE — persist selections (if not already)
══════════════════════════════════════════════════════════════

On scan create / update, save category_selections JSONB on shelf_scans
(alongside legacy category + sub_category columns).

On scan history + results page, read category_selections for header chips.
Do not rely on sub_category alone when array exists.

══════════════════════════════════════════════════════════════
3. ASSIGN-SCAN PRE-FILL
══════════════════════════════════════════════════════════════

When opening /scan from assignment with scope_type sub_category and
scope_values.category_selections — pre-fill picker AND send same array on POST /scan.

══════════════════════════════════════════════════════════════
4. MIXED SNACK RACK (same pattern)
══════════════════════════════════════════════════════════════

Packaged Food & Snacks with Chips + Biscuits + Namkeen tags:
  category_selections: [
    { category_name: "Packaged Food & Snacks", sub_category_id: "chips", sub_category_label: "Chips" },
    { category_name: "Packaged Food & Snacks", sub_category_id: "biscuits", sub_category_label: "Biscuits" },
    { category_name: "Packaged Food & Snacks", sub_category_id: "namkeen", sub_category_label: "Namkeen" }
  ]

══════════════════════════════════════════════════════════════
5. DO NOT CHANGE
══════════════════════════════════════════════════════════════

- Planogram CSV schema (one category + sub_category per product row)
- GET /categories response
- Scan UX for adding/removing chips (already built if multi picker exists)

══════════════════════════════════════════════════════════════
6. TEST CHECKLIST
══════════════════════════════════════════════════════════════

1. Add Shampoo + Soap + Deodorant tags on /scan → DevTools Network → POST /scan body contains category_selections with 3 entries

2. Run scan on mixed PC shelf (A-1-Z) → misplaced facings near 0, not 20+

3. Single-tag scan (Chips only) → still works; legacy fields present

4. Assign scan with 2 scope pairs → assignee POST /scan includes both in category_selections

5. Scan history shows all tags from stored category_selections

Publish when done.
```

---

## Quick dev check (browser DevTools)

After Lovable publish, start a multi-tag scan and confirm the request body includes:

```json
"category_selections": [ /* length = number of chips */ ]
```

If missing, the backend falls back to `sub_category` only (first tag).
