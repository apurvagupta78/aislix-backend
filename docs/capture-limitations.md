# Capture Limitations & Capability Tiers

A single front-facing mobile photograph provides **point-in-time visible evidence** — not complete inventory, hidden depth, or confirmed historical stockouts.

---

## Tier A — Photo observations (no planogram required)

Available when evidence supports:

- Visible product fronts / facings  
- Brand and category identification (where confident)  
- Visual product groups when exact SKU unresolved  
- Shelf rows and relative positions  
- Brand/category facing mix (scoped correctly)  
- Visible gaps, orientation, obstruction  
- Readable pack text and pack size (quality-dependent)  
- Visible shelf-label text and prices (when readable)  
- Recognition coverage and unresolved detections  
- Evidence crops and annotated positions  

---

## Tier B — Photo + catalog / assortment / planogram

- Exact target matching (when identity established)  
- Required-product presence  
- Photo-assessed availability (with coverage bounds)  
- Facing-target compliance  
- Position/sequence compliance  
- Intrusion checks (inside designated zones only)  
- Price/promotion compliance (with tag association)  
- Missing expected assortment  

---

## Tier C — Commercial inputs

- Conditional sales exposure scenarios  
- Demand-based opportunity estimates  
- Margin/contribution exposure  
- Action prioritization by modeled benefit  

---

## Tier D — POS / inventory / controlled measurement

- Realized sales and margins  
- Inventory cover and stock projections  
- Time-based availability  
- Incremental profit measurement (DiD, RCT)  

---

## Never infer from one front-facing photo alone

- Hidden depth or backroom stock  
- Actual stockout duration  
- Actual sales velocity or lost sales  
- Shopper conversion or market share  
- All expiry dates  
- Physical centimeters without calibration  
- Actual realized profit  

---

## Capture pipeline requirements

1. **Pre-upload guidance:** blur, glare, exposure, perspective, cropping  
2. **Bay/ROI selection** with frame-edge exclusion rules (`app/audit_scope.py`)  
3. **Per-facing evidence** or explicit count-estimate evidence  
4. **Separate OCR regions** for products vs shelf labels  
5. **Product-tag association** with its own confidence  
6. **Multi-photo fallback** when shelf exceeds one useful frame  
7. **Deduplicate overlapping views** — never dedupe all instances of same SKU  
8. **Keep unrecognized products visible** for human review  

A single useful photo is the happy path — not a reason to manufacture evidence.

---

## Scope rules (Colgate case)

| Observation | In toothpaste share denominator? | Placement intrusion? |
|-------------|----------------------------------|----------------------|
| Toothpaste facings | Yes | N/A |
| Unclassified toothpaste facings | Yes (shown separately) | No |
| Mouthwash in same photo | No | Only if inside toothpaste-only zone |
| Water at frame edge / adjacent bay | No | No |

Taxonomy mismatch alone ≠ wrong placement.

---

## Quality scoring

Task-specific and spatial:

- **Detection quality** — adequate for facing counts?  
- **OCR quality** — pack text readable?  
- **Price-tag quality** — tags readable and associable?  

Do not emit unsupported perfect scores (e.g. 100/100 without basis).

---

## Provenance labels

Every result should indicate:

- `live` | `cached` | `demo`  
- Capture timestamp (store timezone)  
- Model / formula / catalog versions  
- Measured end-to-end timing (not inference ms alone)
