# Shelf detection benchmark (Phase 0)

Measure **facing count** and (optionally) **SKU identification** on real phone shelf photos before/after model changes (SAHI, retrain, etc.).

## Setup

1. Copy shelf photos into `data/benchmark/images/`:
   - `shampoo_a1z.jpg` — A-1-Z 8-SKU shampoo row
   - `tea_a1s.jpg` — A-1-S 7-SKU tea row
   - `ice_cream_a1s.jpg` — A-1-S freezer (5 planogram SKUs; copy from your scan photo)

2. Optional: add per-facing ground truth in `manifest.json`:

```json
"facings": [
  {
    "brand": "Dove",
    "product_name": "Intense Repair Shampoo",
    "box": [120, 80, 220, 520]
  }
]
```

Boxes are pixel coordinates `[x1, y1, x2, y2]` on the oriented photo (same as upload).

3. Run evaluation:

```powershell
cd C:\Users\Apaar\PycharmProjects\aislix-backend
py scripts/eval_accuracy.py
py scripts/eval_accuracy.py --full-scan
py scripts/eval_benchmark.py
py scripts/eval_benchmark.py --mode sahi
py scripts/eval_benchmark.py --compare
py scripts/eval_ocr_crops.py
py scripts/report_category_coverage.py
```

Reports are written to `data/benchmark/reports/`.

See **`docs/ACCURACY_IMPROVEMENT.md`** for the full cross-category improvement loop.

## Metrics

| Metric | Meaning |
|--------|---------|
| **Facing recall** | Matched GT boxes / total GT boxes (IoU ≥ 0.5) |
| **Facing precision** | Matched preds / total predictions |
| **Count error** | \|predicted count − expected count\| when boxes not labeled |

## Enable SAHI in production

Railway env:

```
DETECTION_MODE=sahi
```

Optional tuning:

```
SAHI_TILE_SIZE=640
SAHI_OVERLAP_RATIO=0.25
SAHI_INCLUDE_FULL_FRAME=true
```

Default remains `DETECTION_MODE=standard` until benchmark shows SAHI wins on your images.
