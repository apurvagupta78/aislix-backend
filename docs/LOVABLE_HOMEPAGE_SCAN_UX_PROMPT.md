# Lovable Prompt — Homepage Default Shelf Image + Scan Progress UX

Paste this **entire block** into Lovable chat → **Publish** to `https://aislix.com/`.

**Backend API:** `https://aislix-backend-production.up.railway.app`  
**Env:** `VITE_AISLIX_API_URL=https://aislix-backend-production.up.railway.app`

**Default sample (toothpaste shelf — use everywhere on homepage / landing demo):**

```
export const DEFAULT_SAMPLE_ID = "toothpaste-a1l";
export const DEFAULT_SAMPLE_IMAGE =
  `${import.meta.env.VITE_AISLIX_API_URL}/landing/samples/toothpaste-a1l/image`;
```

List all samples: `GET /landing/samples` — default sample has `"is_default": true`.

---

## URGENT FIX — "Failed to fetch" + wrong dummy inventory (paste first if live)

Symptoms on homepage demo:
- Red banner **"Failed to fetch"** but table still shows 8 products / 91% shelf health
- That table is **hardcoded dummy data** from HomeLiveDemoDashboard — NOT real API results

Backend live scan returns **~154 products / 18 SKUs** for `toothpaste-a1l` when called correctly.

### A. Remove dummy fallback on error

DELETE or disable any static demo rows like:
- Colgate Strong Teeth Qty 1, MaxFresh Qty 1, Pepsodent Qty 1
- Metrics 8 / 8 / 91%

On scan error:
- Show sticky error alert with real message (from `response.json().detail` or catch text)
- Keep **metrics + table empty** or show "Scan failed — try again"
- NEVER render dummy inventory when `fetch` fails

### B. Correct API call (src/lib/landing-scan-api.ts)

```typescript
const API = import.meta.env.VITE_AISLIX_API_URL?.replace(/\/$/, "");
if (!API) throw new Error("VITE_AISLIX_API_URL is not configured");

export async function runLandingSample(sampleId = "toothpaste-a1l") {
  const form = new FormData();
  form.append("sample_id", sampleId);
  if (sessionId) form.append("landing_session_id", sessionId);

  const res = await fetch(`${API}/landing/scan`, {
    method: "POST",
    body: form,
    // do NOT set Content-Type — browser sets multipart boundary
  });

  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body?.detail ?? res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}
```

Also supported (simpler): `POST /landing/scan` with JSON `{ "sample_id": "toothpaste-a1l" }`.

Timeout: allow **120 seconds** (large shelves + Make.com). Do not abort at 30s.

### C. Default shelf image

On mount set preview to API image (NOT a local stock photo):
`${API}/landing/samples/toothpaste-a1l/image`

After scan completes, replace with `annotated_image_base64` from response if present.

### D. QA after fix

✓ No "Failed to fetch" on Try Sample Shelf  
✓ Products detected ≈ **150+** (not 8) for toothpaste sample  
✓ Unique SKUs ≈ **14–18** (not 8)  
✓ On error: no fake inventory rows  

---

```
HOMEPAGE + LANDING DEMO — DEFAULT SHELF IMAGE + SCAN PROGRESS UX

DO NOT MODIFY: /signup, /login, /dashboard auth, Supabase core, existing scan API contracts.
UPDATE: homepage hero preview, live demo scan UI on / and /retail-intelligence (if present).

══════════════════════════════════════════════════════════════
1. DEFAULT SHELF IMAGE (toothpaste rack)
══════════════════════════════════════════════════════════════

Replace shampoo / Lay's placeholder with the new default sample everywhere users see
a shelf photo BEFORE or DURING a demo scan:

  sample_id: toothpaste-a1l
  image URL: ${VITE_AISLIX_API_URL}/landing/samples/toothpaste-a1l/image

Apply on:
  • Homepage hero "SHELF PHOTO" card (HomeScanHero or equivalent)
  • Homepage live demo left panel — show this image on mount (never empty gray box)
  • /retail-intelligence LiveDemoSection preview + default Try Sample Shelf target
  • Any marketing "Try sample shelf" CTA

On mount / page load:
  setPreviewImageUrl(DEFAULT_SAMPLE_IMAGE)

"Try Sample Shelf" button:
  POST /landing/scan with sample_id=toothpaste-a1l (or omit sample_id — backend default is toothpaste-a1l)

Keep lays-a1l and shampoo-a1z available if you have a sample picker — but toothpaste-a1l is DEFAULT.

══════════════════════════════════════════════════════════════
2. SCANNING STATE — messages + progress bar (match dashboard)
══════════════════════════════════════════════════════════════

While POST /landing/scan is in flight (homepage demo OR logged-in scan if shared component),
replace generic spinner-only UI with the SAME progress experience as dashboard new-scan.

FIND the existing dashboard scan progress component (e.g. ScanProgress, ScanProcessingOverlay,
NewScanProgress, or similar in src/components/scan/ or dashboard routes) and REUSE it —
do NOT invent a new thin spinner.

If no shared component exists yet, extract dashboard scan progress into:
  src/components/scan/ScanProgressPanel.tsx
and use it from BOTH dashboard and homepage demo.

Required copy (show all three while status === "scanning" | "processing"):

  A. Primary status line (bold):
     "Analyzing shelf…"

  B. Timing guidance (muted, always visible during scan):
     "This usually takes less than 60 seconds for large shelves. Keep this page open."

  C. Progress bar (match dashboard exactly):
     • Same height, color (primary/navy), rounded bar + animated indeterminate OR stepped progress
     • Same animation timing as dashboard — NOT a tiny CSS spinner alone
     • If dashboard shows elapsed time or phase labels ("Detecting products…", "Building report…"),
       show the same phases on homepage demo

  D. AI disclaimer (small text below bar, always visible during + after scan):
     "AI can make mistakes. Verify critical counts before acting on results."

Layout during scan:
  • Keep shelf photo visible (toothpaste default or user upload) — do NOT blank the image
  • Semi-transparent overlay on image optional: "Analyzing shelf…"
  • Progress panel on the RIGHT (demo) or centered modal (mobile) — same structure as dashboard

After scan completes:
  • Hide progress bar
  • Keep disclaimer visible in results footer or under executive summary:
    "AI can make mistakes. Verify critical counts before acting on results."

══════════════════════════════════════════════════════════════
3. FILES TO TOUCH (typical)
══════════════════════════════════════════════════════════════

  src/lib/landingSamples.ts — DEFAULT_SAMPLE_ID = "toothpaste-a1l"
  src/components/home/HomeScanHero.tsx — hero shelf photo URL
  src/components/home/HomeLiveDemoDashboard.tsx — default preview + scan state
  src/components/landing/retail-intelligence/LiveDemoSection.tsx — if exists
  src/components/scan/ScanProgressPanel.tsx — shared progress UI (extract if needed)
  src/routes/index.tsx — wire shared progress into homepage demo

══════════════════════════════════════════════════════════════
4. QA CHECKLIST
══════════════════════════════════════════════════════════════

✓ Homepage loads with toothpaste shelf photo visible (not empty placeholder)
✓ Try Sample Shelf runs scan with toothpaste-a1l
✓ While scanning: timing message "less than 60 seconds… Keep this page open"
✓ While scanning: progress bar matches dashboard (not spinner-only)
✓ Disclaimer "AI can make mistakes" visible during scan and after results
✓ Image stays visible during scan
✓ Mobile: stacked layout, progress bar full width
✓ Dashboard scan flow unchanged (same shared component)

Publish when complete.
```
