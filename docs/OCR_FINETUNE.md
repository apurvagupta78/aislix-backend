# PaddleOCR fine-tuning on Aislix shelf crops

Use this when generic Paddle models plateau on Indian FMCG packaging (stylized fonts, Hindi/regional text, glossy glare).

## 1. Build a labeled crop dataset

Add facing boxes + ground-truth text to `data/benchmark/manifest.json`:

```json
{
  "id": "r2c1",
  "brand": "Lays",
  "product_name": "Indias Magic Masala Potato Chips",
  "ocr_label": "Lay's India's Magic Masala",
  "box": [0.05, 0.12, 0.12, 0.22]
}
```

Export crops:

```powershell
py scripts/prepare_ocr_finetune_dataset.py
```

Output: `data/ocr_finetune/images/` + `labels.csv`.

## 2. Fine-tune recognition model (Colab or local GPU)

Follow [PaddleOCR text recognition fine-tuning](https://github.com/PaddlePaddle/PaddleOCR/blob/main/doc/doc_en/recognition_en.md):

- Base: `PP-OCRv4_mobile_rec` or `PP-OCRv4_server_rec`
- Train on `labels.csv` (one image path + tab-separated label per line)
- Target: **CER < 8%** on held-out facings before deploy

## 3. Deploy custom weights on Railway

Upload the fine-tuned inference model folder and set:

```env
OCR_PADDLE_REC_MODEL_DIR=/app/models/aislix_rec
OCR_PADDLE_REC_MODEL=custom
```

The backend loads custom rec weights when `OCR_PADDLE_REC_MODEL_DIR` is set.

## 4. Continuous learning loop

1. Scan → low `ocr_confidence` facings flagged in metrics
2. Human corrects SKU in Lovable / CVAT
3. Append crop + label to benchmark manifest
4. Re-export → re-train → redeploy

This closes the loop toward 95%+ on representative store photos.
