# Grocer-Help YOLO training (Phase 1 + 2)

Indian FMCG shelf dataset: **647 SKU classes**, ~6,751 train / 689 valid images (~4 GB).

## Step 0 — Extract dataset

```powershell
Expand-Archive -Path "D:\Grocer-Help.zip" -DestinationPath "D:\"
# Creates D:\Grocer-Help\ with train/, valid/, data.yaml
```

## Step 1 — Prepare configs

```powershell
cd C:\Users\Apaar\PycharmProjects\aislix-backend
py -m pip install pyyaml ultralytics  # if needed

py scripts/prepare_grocer_help.py --source "D:\Grocer-Help" --audit
```

Outputs in `D:\Grocer-Help\`:

| File | Use |
|------|-----|
| `data.single_class.yaml` | **Phase 1** — fine-tune `best.pt` (detection / counting) |
| `data.fixed.yaml` | **Phase 2A** — 647-class multi-class YOLO |
| `data/grocer_help/class_names.json` | Class id → brand name mapping |

Smoke-test subset (200 images):

```powershell
py scripts/prepare_grocer_help.py --source "D:\Grocer-Help" --output data/grocer_help --max-train 200
```

---

## Phase 1 — Fine-tune current `best.pt` on Google Colab (recommended)

1. Upload to Google Drive:
   - `D:\Grocer-Help\` (full folder)
   - `best.pt` from repo root (Git LFS)

2. Open [`notebooks/train_yolo_grocer_help_colab.ipynb`](../notebooks/train_yolo_grocer_help_colab.ipynb) in Colab.

3. Run all cells — trains from **`best.pt`** using `data.single_class.yaml`.

4. Download `runs/shelf_detector/train/weights/best.pt` from Colab.

---

## Step 2 — Benchmark gate (required before deploy)

Copy new weights locally, then:

```powershell
copy path\to\new\best.pt C:\Users\Apaar\PycharmProjects\aislix-backend\best.pt

py scripts/eval_benchmark.py --compare
```

**Pass criteria:**

| Case | Target |
|------|--------|
| shampoo_a1z | pred ≥ 8 facings |
| tea_a1s | pred ≥ 7 facings |
| ice_cream_a1s | pred ≥ expected (see manifest) |
| Precision | Must not collapse (SAHI previously over-counted 14 vs 8) |

Add your freezer photo for ice cream benchmark:

```powershell
copy your_freezer.jpg data\benchmark\images\ice_cream_a1s.jpg
```

---

## Step 3 — Deploy to Railway

```powershell
git add best.pt
git commit -m "Fine-tune YOLO on Grocer-Help Indian shelf dataset."
git push origin main
```

Keep `DETECTION_MODE=standard` on Railway (do not enable SAHI unless benchmark proves it).

---

## Phase 2B — SKU embeddings (all categories)

Build visual fingerprints for **all 647 Grocer-Help SKUs**, mapped to Aislix categories
(tea, shampoo, snacks, dairy, home care, frozen, etc.) — not just ice cream.

### Step 1 — Build embeddings (Colab recommended)

```python
# Colab cell — after Grocer-Help zip is on Drive
!pip install -q opencv-python-headless pyyaml
import os, zipfile
from pathlib import Path

zip_path = Path('/content/drive/MyDrive/Aislix/Grocer-Help.zip')
extract = Path('/content/grocer_help')
if not (extract / 'Grocer-Help' / 'train').exists():
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(extract)
source = extract / 'Grocer-Help' if (extract / 'Grocer-Help' / 'train').exists() else extract

!git clone -q https://github.com/apurvagupta78/aislix-backend.git /content/aislix-backend
os.chdir('/content/aislix-backend')
!python scripts/build_grocer_help_embeddings.py --source "{source}" --crops-per-sku 3
```

Output:
- `data/grocer_help/embeddings.json` (~647 SKUs)
- `data/grocer_help/embeddings_by_category.json` (counts per category)

### Step 2 — Import to learned catalog + Supabase

On Railway (or locally with `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`):

```powershell
py scripts/import_grocer_help_embeddings.py --upload --global-table
```

Or Colab:

```python
import os
os.environ['SUPABASE_URL'] = 'your-url'
os.environ['SUPABASE_SERVICE_ROLE_KEY'] = 'your-key'
!python scripts/import_grocer_help_embeddings.py --input data/grocer_help/embeddings.json --upload --global-table
```

### Step 3 — Redeploy / restart Railway

Railway loads learned SKUs on startup. Lovable also sends `learned_catalog` on each scan.

### Phase 2C — Category-scoped learned search

Learned FAISS search filters by scan category + sub-category (all aisles), preventing
cross-category false matches (e.g. protein bar on a tea shelf).

### What improves (all aisles)

| Category | Example SKUs in Grocer-Help |
|----------|----------------------------|
| Beverages · Tea | TajMahal, Lipton, RedLabel, Tetley, BrookeBond |
| Personal Care · Shampoo | Tresemme, Dove, Head & Shoulders, Pantene |
| Packaged Food · Snacks | Lays, Haldirams, Parle, Britannia |
| Dairy | Amul, Mother Dairy, cheese, lassi |
| Grocery · Staples | Rice, oil, masala, MDH, Everest |
| Frozen · Ice cream | Generic `IceCream` class only |

**Not in dataset:** Brooklyn, Amul Sandwich — add via scan corrections (learned SKU) or future custom crops.

---

## Local training (if you have NVIDIA GPU)

```powershell
py scripts/train_yolo_shelf.py ^
  --dataset "D:\Grocer-Help" ^
  --data-yaml data.single_class.yaml ^
  --epochs 50 ^
  --batch 8 ^
  --device 0 ^
  --copy-to-repo
```

---

## What improves

| Phase | Helps |
|-------|--------|
| Phase 1 | Facing detection + **quantity** (more boxes on Indian shelves) |
| Phase 2B | **SKU names** for 647 in-dataset brands (Amul, TajMahal, Tresemme, …) |
| Phase 2A | Optional 647-class detector (larger change) |

SKUs **not** in Grocer-Help (e.g. Brooklyn) still need FAISS/OCR/planogram.
