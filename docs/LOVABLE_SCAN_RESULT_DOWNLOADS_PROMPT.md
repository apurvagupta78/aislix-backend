# Lovable Prompt — Scan result downloads (annotated image + PDF)

Paste into Lovable after deploying latest Railway backend (PDF now embeds annotated shelf image).

---

```
Fix scan result page downloads — annotated image must DOWNLOAD (not open in browser).

## Problem (from scan result / results page)

1. **Downloads section** → "Annotated image" button opens image in a new tab instead of downloading.
2. **Annotated shelf image viewer** → top-right "Image" button also opens in browser instead of downloading.
3. PDF report is missing annotated shelf image — **backend fix deployed**; new scans get PDF with image embedded. Re-scan or call export-assets for old scans.

## STEP 1 — Ensure helpers exist in `src/lib/scan-results.ts`

Copy from backend repo `docs/scan-downloads.ts`:

- `downloadFileFromUrl(url, filename)` — fetch → blob → `<a download>` click (NOT window.open)
- `downloadScanAnnotatedImage(scanId, imageUrl?)`
- `downloadScanPdf(scanId, pdfUrl?)`

```ts
export async function downloadFileFromUrl(url: string, filename: string): Promise<void> {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Could not download the file.");
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

export async function downloadScanAnnotatedImage(scanId: string, imageUrl?: string): Promise<void> {
  const url = imageUrl ?? (await resolveScanAssetUrls(scanId)).annotated_image_url;
  if (!url) throw new Error("Annotated shelf image is not available for this scan yet.");
  const ext = url.includes(".png") ? "png" : "jpg";
  await downloadFileFromUrl(url, `aislix-${scanId}-annotated.${ext}`);
}
```

## STEP 2 — Downloads section (scan result page)

Find the "Downloads" card with buttons: PDF report, CSV inventory, **Annotated image**, Print report, JSON payload.

Replace annotated image handler:

```tsx
// BAD — opens in browser:
window.open(url, "_blank");
// or <a href={url} target="_blank">

// GOOD:
import { downloadScanAnnotatedImage } from "@/lib/scan-results";

<Button
  variant="outline"
  onClick={async () => {
    try {
      await downloadScanAnnotatedImage(scanId, downloads?.annotated_image_url);
      toast.success("Annotated image downloaded");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Download failed");
    }
  }}
>
  Annotated image
</Button>
```

Same for **PDF report** — use `downloadScanPdf`, not `window.open`.

## STEP 3 — Annotated shelf image viewer ("Image" button top-right)

In the annotated image panel component (zoom +/-, fullscreen, **Image** download):

```tsx
<Button
  variant="outline"
  size="sm"
  onClick={async () => {
    try {
      await downloadScanAnnotatedImage(scanId, annotatedUrl);
      toast.success("Image downloaded");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Download failed");
    }
  }}
>
  <Download className="h-4 w-4 mr-1" />
  Image
</Button>
```

If showing base64 from scan payload (before storage upload), fallback:

```ts
function downloadBase64Image(base64: string, filename: string) {
  const link = document.createElement("a");
  link.href = `data:image/jpeg;base64,${base64}`;
  link.download = filename;
  link.click();
}
```

## STEP 4 — PDF includes annotated image (backend)

No frontend change needed for PDF content — Railway now embeds annotated shelf image in every new scan PDF.

For **old scans** without updated PDF: call `ensureScanAssets(scanId)` or POST `/scan/export-assets` then re-store PDF.

## TEST

1. Complete a new scan → Downloads → Annotated image → file saves as `aislix-{id}-annotated.jpg` (not new tab)
2. Annotated shelf viewer → Image button → same download behavior
3. PDF report → open → contains "Annotated Shelf Image" section with green boxes
4. Mobile Safari/Chrome → download works (blob method, not window.open)

Do not change Railway backend in Lovable.
```
