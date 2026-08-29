# Lovable Prompt — `/retail-intelligence` Minimal Lead Landing (v2)

Paste into Lovable chat → **Publish** to `https://aislix.com/retail-intelligence`.

**Backend:** `https://aislix-backend-production.up.railway.app`  
**Env:** `VITE_AISLIX_API_URL=https://aislix-backend-production.up.railway.app`

---

```
RETAIL INTELLIGENCE — STRIP TO MINIMAL LEAD LANDING PAGE (v2)

CRITICAL — DO NOT TOUCH:
- Homepage "/" (src/routes/index.tsx) — unchanged
- /signup, /login, /dashboard auth flows (small additive hooks only)
- LinkedIn Insight Tag

ONLY REWRITE:
- /retail-intelligence page + components in src/components/landing/retail-intelligence/
- src/lib/landing-scan-api.ts

══════════════════════════════════════════════════════════════
WHAT IS WRONG TODAY — FIX ALL OF THIS
══════════════════════════════════════════════════════════════

1. Page looks like a full marketing homepage (hero, how-it-works, capabilities, use cases) — REMOVE ALL THAT.
   This is a LinkedIn ad landing page. User should see ONLY: headline → live demo → lead form.

2. Clicking "Try Sample Shelf" shows empty left panel while scanning — WRONG.
   Show the shelf image IMMEDIATELY while AI runs (see Step 3).

3. Results table shows "Compliance / On planogram" — WRONG for demo scans (no planogram uploaded).
   Backend now returns scan_mode: "audit_only", has_planogram: false, status_label per row.
   Hide Compliance column entirely. Use Status column: "Detected" | "Needs review".

4. No CSV download — ADD "Download CSV" button after results.

5. Too many nav links and CTAs to /signup before scan — simplify nav to logo + Log in only.

══════════════════════════════════════════════════════════════
PAGE STRUCTURE (ONLY 3 SECTIONS)
══════════════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────┐
│  [AISLIX logo]                              [Log in]    │  ← minimal header
├─────────────────────────────────────────────────────────┤
│  H1: Turn Any Shelf Photo Into Retail Intelligence      │  ← compact hero (1 screen max)
│  1-line subhead + trust: "3 free scans • No credit card"│
├─────────────────────────────────────────────────────────┤
│  LIVE DEMO (id="demo") — full width, main focus         │
│  [Try Sample Shelf] [Upload Shelf Photo]                │
│  ┌──────────────────┬──────────────────────────────┐    │
│  │ Shelf image      │ Results / scanning state     │    │
│  └──────────────────┴──────────────────────────────┘    │
│  [Download CSV]  (after results)                        │
├─────────────────────────────────────────────────────────┤
│  LEAD CAPTURE (id="lead") — appears after scan results  │
│  Email + Name + Company → Continue → Create account     │
├─────────────────────────────────────────────────────────┤
│  Minimal footer: © Aislix • Privacy • Terms             │
└─────────────────────────────────────────────────────────┘

DELETE these sections entirely if they exist:
  #how-it-works, #capabilities, #use-cases, #problem, #product-output,
  long hero with dashboard screenshot, 3-step flow diagram, duplicate CTAs.

DO NOT link logo to "/" — keep user on landing: logo → /retail-intelligence

══════════════════════════════════════════════════════════════
STEP 1 — API CLIENT (src/lib/landing-scan-api.ts)
══════════════════════════════════════════════════════════════

const API = import.meta.env.VITE_AISLIX_API_URL;

export type LandingScanResult = {
  landing_session_id: string;
  scan_id: string;
  status: "completed";
  scan_mode: "audit_only";
  has_planogram: false;
  metrics: { total_products?: number; unique_skus?: number; shelf_health_score?: number };
  inventory: Array<{
    brand: string;
    product_name: string;
    quantity: number;
    confidence?: number;
    status_label?: "Detected" | "Needs review";
    counted_in_totals?: boolean;
  }>;
  executive_summary?: string;
  annotated_image_base64?: string;
  annotated_image_mime?: string;
  original_image_base64?: string;
  original_image_mime?: string;
  csv_base64?: string;
  scans_used_today?: number;
  scans_daily_limit?: number;
};

const SAMPLE_PREVIEW_URL = `${API}/landing/samples/lays-a1l/image`;

export function getSamplePreviewUrl(sampleId = "lays-a1l") {
  return `${API}/landing/samples/${sampleId}/image`;
}

function appendUtm(form: FormData) {
  const p = new URLSearchParams(window.location.search);
  for (const k of ["utm_source","utm_medium","utm_campaign","utm_content","utm_term"]) {
    const v = p.get(k);
    if (v) form.append(k, v);
  }
}

export async function runLandingSample(sampleId = "lays-a1l", sid?: string) {
  const form = new FormData();
  form.append("sample_id", sampleId);
  if (sid) form.append("landing_session_id", sid);
  appendUtm(form);
  const res = await fetch(`${API}/landing/scan`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Scan failed");
  return res.json() as Promise<LandingScanResult>;
}

export async function runLandingScan(file: File, sid?: string) {
  const form = new FormData();
  form.append("file", file);
  if (sid) form.append("landing_session_id", sid);
  appendUtm(form);
  const res = await fetch(`${API}/landing/scan`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Scan failed");
  return res.json() as Promise<LandingScanResult>;
}

export function downloadLandingCsv(result: LandingScanResult) {
  if (!result.csv_base64) return;
  const bytes = Uint8Array.from(atob(result.csv_base64), c => c.charCodeAt(0));
  const blob = new Blob([bytes], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `aislix-shelf-scan-${result.scan_id || "demo"}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export async function captureLandingLead(payload: {
  landing_session_id: string; email: string; name?: string; company?: string;
}) {
  await fetch(`${API}/landing/lead`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function convertLandingSession(sid: string, userId: string) {
  await fetch(`${API}/landing/convert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ landing_session_id: sid, user_id: userId }),
  });
}

export function persistLandingSession(r: LandingScanResult) {
  sessionStorage.setItem("aislix_landing_session_id", r.landing_session_id);
  sessionStorage.setItem("aislix_landing_scan_result", JSON.stringify(r));
}

export function signupUrlWithLanding() {
  const p = new URLSearchParams(window.location.search);
  const sid = sessionStorage.getItem("aislix_landing_session_id");
  if (sid) p.set("landing_session_id", sid);
  const qs = p.toString();
  return qs ? `/signup?${qs}` : "/signup";
}

══════════════════════════════════════════════════════════════
STEP 2 — DEMO UI (MOST IMPORTANT)
══════════════════════════════════════════════════════════════

Component: RetailIntelligenceDemo.tsx

Layout: 2-column on desktop (image left 55%, results right 45%), stacked on mobile.

TABS:
  • "Try Sample Shelf" → handleSampleScan()
  • "Upload Shelf Photo" → hidden file input

IMAGE PANEL — FIX EMPTY STATE DURING SCAN:

  State: previewImageUrl: string | null

  On "Try Sample Shelf" click — BEFORE fetch:
    setPreviewImageUrl(getSamplePreviewUrl("lays-a1l"));
    setPhase("scanning");

  On file upload — BEFORE fetch:
    const url = URL.createObjectURL(file);
    setPreviewImageUrl(url);
    setPhase("scanning");

  While scanning:
    LEFT panel MUST show previewImageUrl (NOT empty placeholder text)
    Overlay subtle pulse on image + badge "Analyzing…"
    RIGHT panel: spinner + "Analyzing shelf… 30–90s"

  On success:
    Replace preview with annotated image:
      src={`data:${result.annotated_image_mime};base64,${result.annotated_image_base64}`}
    If annotated missing, fallback to original_image_base64

RESULTS PANEL (right):

  Metrics row (3 cards):
    Products detected → metrics.total_products
    Unique SKUs → metrics.unique_skus
    Shelf health → metrics.shelf_health_score

  Executive summary paragraph (1–2 lines max)

  Table columns — NO PLANogram:
    Brand | Product | Qty | Conf. | Status
    Status from inventory[].status_label ("Detected" | "Needs review")
    NEVER show "On planogram" or "Compliance" on this page
    If has_planogram === false (always for landing), do not render planogram UI

  Footer line: "{scans_used_today} of {scans_daily_limit} free demo scans used today"

  Actions row below table:
    [Download CSV] → downloadLandingCsv(result) — outline button with Download icon
    Disabled until result.csv_base64 exists

DO NOT use static/hardcoded demo data. All from API response.

══════════════════════════════════════════════════════════════
STEP 3 — LEAD CAPTURE (id="lead")
══════════════════════════════════════════════════════════════

Show ONLY after scan completes (scroll into view smoothly).

Card design — clean white card, subtle border, centered max-w-lg:

  H2: Save your results & analyze more shelves
  Sub: Enter your work email to get 3 free shelf scans in your workspace.

  Fields: Email* | Name | Company
  [Continue] → captureLandingLead → show success state:
    "Thanks! Create your free account to continue."
    [Create Free Account →] signupUrlWithLanding()

  Small link: "Skip for now" → signupUrlWithLanding()

Results remain visible above — form does NOT hide or block results.

══════════════════════════════════════════════════════════════
STEP 4 — VISUAL DESIGN (professional ad landing)
══════════════════════════════════════════════════════════════

- Full viewport height demo section — this IS the product
- White/light gray background, navy accent (match existing Aislix brand)
- No marketing fluff below fold
- No duplicate "Start Free Shelf Scan" buttons in header (remove header CTA)
- Header: logo left, "Log in" text link right only
- Typography: one H1, demo H2 "See What Aislix Sees", rest body text
- Mobile: image on top, results below, lead form last
- No sticky bottom bar (cleaner for ad landing)

Reference feel: Stripe/Linear demo pages — product-first, minimal chrome.

══════════════════════════════════════════════════════════════
STEP 5 — SIGNUP HOOK (minimal change to /signup)
══════════════════════════════════════════════════════════════

After signUp success + user.id:
  convertLandingSession(landing_session_id, user.id)

Read landing_session_id from URL query or sessionStorage.

══════════════════════════════════════════════════════════════
STEP 6 — QA CHECKLIST
══════════════════════════════════════════════════════════════

✓ Page has ONLY: compact hero + demo + lead form + minimal footer
✓ No how-it-works / capabilities / use cases sections
✓ Click "Try Sample Shelf" → Lay's image appears IMMEDIATELY on left
✓ After ~60s → annotated image + real inventory on right
✓ No "On planogram" or Compliance column anywhere
✓ Download CSV works and file opens in Excel
✓ Lead form appears after results
✓ / unchanged, /retail-intelligence public, no login required to scan

Publish when done.
```
