# Lovable Prompt — `/retail-intelligence` Professional Lead Landing (v3)

Paste into Lovable → **Publish** to `https://aislix.com/retail-intelligence`.

**Backend API:** `https://aislix-backend-production.up.railway.app`  
**Env var:** `VITE_AISLIX_API_URL=https://aislix-backend-production.up.railway.app`

**Sample image (always visible by default):**  
`https://aislix-backend-production.up.railway.app/landing/samples/lays-a1l/image`

---

```
/retail-intelligence — REBUILD AS PROFESSIONAL LINKEDIN AD LANDING (v3)

DO NOT MODIFY: "/", /signup, /login, /dashboard core flows, LinkedIn Insight Tag.
ONLY REBUILD: /retail-intelligence + src/components/landing/retail-intelligence/* + src/lib/landing-scan-api.ts

══════════════════════════════════════════════════════════════
BUGS TO FIX FROM CURRENT BUILD
══════════════════════════════════════════════════════════════

❌ Sample image not visible on page load — FIX: show Lay's rack image immediately (see Step 2)
❌ Empty left panel while scanning — FIX: keep preview image visible with "Analyzing…" overlay
❌ Wrong products (Classic Salted, Sizzlin Hot) — backend now uses FULL scan engine + planogram for sample; display API results only
❌ No lead capture form — ADD mandatory lead section (Step 4)
❌ Page still looks like homepage — STRIP to hero + demo + lead only (Step 1)

══════════════════════════════════════════════════════════════
STEP 1 — PAGE LAYOUT (match attached design reference)
══════════════════════════════════════════════════════════════

Visual style (from reference mockup):
- Dark navy hero background (#0B1220 or similar)
- Teal accent CTA buttons (#14B8A6)
- Clean white demo card below hero
- Professional B2B SaaS feel (Stripe / Linear quality)

PAGE SECTIONS — ONLY THESE THREE:

┌─────────────────────────────────────────────────────────────┐
│ SECTION A — HERO (dark navy, full width)                    │
│   Left: H1 "Audit Every Aisle. From a Single Photo."        │
│         Subhead (1 sentence) + trust pills:                 │
│         "No card required" • "3 free scans" • "Results in ~60s"│
│   Right: NO static mockup — real demo starts in Section B   │
├─────────────────────────────────────────────────────────────┤
│ SECTION B — LIVE DEMO (white bg, id="demo") — MAIN PRODUCT  │
│   Headline: "See What Aislix Sees"                          │
│   [Try Sample Shelf]  [Upload Shelf Photo]                  │
│   ┌─────────────────────┬──────────────────────────────┐  │
│   │ SHELF IMAGE         │ RESULTS / SCANNING           │  │
│   │ (always visible)    │                              │  │
│   └─────────────────────┴──────────────────────────────┘  │
│   [Download CSV] after results                              │
├─────────────────────────────────────────────────────────────┤
│ SECTION C — LEAD CAPTURE (id="lead") — REQUIRED             │
│   Dark or light card, prominent, cannot be missing          │
│   Email + Name + Company → Continue → Create Free Account   │
├─────────────────────────────────────────────────────────────┤
│ Minimal footer: © Aislix • Privacy • Terms                  │
└─────────────────────────────────────────────────────────────┘

DELETE entirely if present:
  #how-it-works, #capabilities, #use-cases, #problem, marketing grids,
  duplicate "Start Free Shelf Scan" header buttons, homepage nav links.

Header: AISLIX logo (→ /retail-intelligence) + "Log in" link only. NO other nav.

══════════════════════════════════════════════════════════════
STEP 2 — DEFAULT SAMPLE IMAGE (CRITICAL)
══════════════════════════════════════════════════════════════

On page mount (useEffect), IMMEDIATELY set:

  const SAMPLE_IMAGE = `${import.meta.env.VITE_AISLIX_API_URL}/landing/samples/lays-a1l/image`;
  setPreviewImageUrl(SAMPLE_IMAGE);

The Lay's rack photo MUST be visible in the left panel BEFORE any click.
Do NOT show placeholder text "Your shelf photo appears here" when previewImageUrl is set.

Left panel render logic:
  if (previewImageUrl) → <img src={previewImageUrl} alt="Sample Lay's chip rack" className="w-full h-full object-contain" />
  if (phase === "scanning") → overlay badge "Analyzing shelf…" on top of image (do NOT hide image)
  if (phase === "done" && result?.annotated_image_base64) → replace with annotated data-URI

Initial state: phase = "idle", previewImageUrl = SAMPLE_IMAGE (set on mount).

══════════════════════════════════════════════════════════════
STEP 3 — SCAN FLOW (same engine as production app)
══════════════════════════════════════════════════════════════

src/lib/landing-scan-api.ts:

const API = import.meta.env.VITE_AISLIX_API_URL;

export const DEFAULT_SAMPLE_ID = "lays-a1l";
export const DEFAULT_SAMPLE_IMAGE = `${API}/landing/samples/${DEFAULT_SAMPLE_ID}/image`;

export async function runLandingSample(sampleId = DEFAULT_SAMPLE_ID, sid?: string) {
  const form = new FormData();
  form.append("sample_id", sampleId);
  if (sid) form.append("landing_session_id", sid);
  // append utm_* from URL
  const res = await fetch(`${API}/landing/scan`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json().catch(()=>({}))).detail || "Scan failed");
  return res.json();
}

export async function runLandingUpload(file: File, sid?: string) { /* same pattern with form.append("file", file) */ }

export function downloadLandingCsv(result: { csv_base64?: string; scan_id?: string }) {
  if (!result.csv_base64) return;
  const bytes = Uint8Array.from(atob(result.csv_base64), c => c.charCodeAt(0));
  const blob = new Blob([bytes], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `aislix-shelf-scan-${result.scan_id || "demo"}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// captureLandingLead, convertLandingSession, persistLandingSession, signupUrlWithLanding — keep from prior implementation

"Try Sample Shelf" button handler:
  1. setPhase("scanning") — image stays visible (previewImageUrl unchanged)
  2. const result = await runLandingSample()
  3. persistLandingSession(result)
  4. setResult(result); setPhase("done")
  5. Show annotated image on left; metrics + table on right
  6. scrollTo(#lead) smoothly after 1s

"Upload Shelf Photo" handler:
  1. User picks file → setPreviewImageUrl(URL.createObjectURL(file)) IMMEDIATELY
  2. setPhase("scanning") → runLandingUpload(file) → same as above

RESULTS TABLE — columns:
  Brand | Product | Qty | Conf. | Status

  Use result.inventory[].status_label → "Detected" | "Needs review"
  NEVER show "Compliance", "On planogram", or planogram columns
  (Backend sets has_planogram for sample internally — do not surface planogram UI)

METRICS (from result.metrics):
  Products detected → total_products
  Unique SKUs → unique_skus
  Shelf health → shelf_health_score

Below table: "{scans_used_today} of {scans_daily_limit} free demo scans used today"

Below demo: [Download CSV] button (outline, Download icon) → downloadLandingCsv(result)

══════════════════════════════════════════════════════════════
STEP 4 — LEAD CAPTURE (MUST EXIST — currently missing)
══════════════════════════════════════════════════════════════

Section id="lead" — always on page, scroll-into-view after first scan.

Design: centered card, max-w-xl, shadow, professional.

  Eyebrow: "Continue with Aislix"
  H2: "Save your shelf audit & unlock 3 free scans"
  Sub: "Enter your work email. No credit card required."

  Form:
    Email *     (type=email, required)
    Full name   (optional)
    Company     (optional)

  Primary button (teal): "Continue"
    → await captureLandingLead({ landing_session_id, email, name, company })
    → show inline success + second CTA

  After submit success:
    "You're all set."
    [Create Free Account →] links to signupUrlWithLanding()

  Secondary link: "Skip for now" → signupUrlWithLanding()

Lead section is visible on page load (below demo) but user scrolls to it after scan.
Do NOT hide lead form behind signup gate before scan.

Also add small lead prompt INSIDE results panel after scan:
  "Want to save this audit?" → scroll to #lead

══════════════════════════════════════════════════════════════
STEP 5 — HERO CTAs
══════════════════════════════════════════════════════════════

Primary (teal): "Try Sample Shelf" → triggers handleSampleScan() + scroll to #demo
Secondary (outline white): "Upload Your Shelf Photo" → opens file picker + scroll to #demo

Do NOT link hero buttons to /signup.

══════════════════════════════════════════════════════════════
STEP 6 — SIGNUP CONVERSION HOOK
══════════════════════════════════════════════════════════════

On /signup after successful signUp:
  if (landing_session_id) convertLandingSession(landing_session_id, user.id)

Read landing_session_id from URL ?landing_session_id= or sessionStorage.

══════════════════════════════════════════════════════════════
STEP 7 — RESPONSIVE
══════════════════════════════════════════════════════════════

Desktop: demo 2-column (55% image / 45% results)
Mobile: image stacked above results; lead form full width
Hero: stack text above demo on mobile

══════════════════════════════════════════════════════════════
STEP 8 — QA (must pass before publish)
══════════════════════════════════════════════════════════════

✓ Page load → Lay's rack image visible immediately (no click needed)
✓ Click "Try Sample Shelf" → image stays visible, spinner on right, ~60s wait
✓ Results show Indian Lay's variants (Magic Masala, Tomato Tango, Cream & Onion) — NOT US flavors
✓ Annotated image replaces preview when done
✓ Download CSV works
✓ Lead form exists with Email/Name/Company and submits to POST /landing/lead
✓ No planogram/compliance columns in table
✓ Page has ONLY hero + demo + lead + footer (no homepage sections)
✓ / unchanged

Publish when QA passes.
```
