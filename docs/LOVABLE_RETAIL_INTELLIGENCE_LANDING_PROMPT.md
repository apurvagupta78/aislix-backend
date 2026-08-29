# Lovable Prompt — `/retail-intelligence` Final Professional Landing Page (v4)

Paste this **entire block** into Lovable chat → **Publish** to `https://aislix.com/retail-intelligence`.

**Backend API:** `https://aislix-backend-production.up.railway.app`  
**Env:** `VITE_AISLIX_API_URL=https://aislix-backend-production.up.railway.app`  
**Default sample image:** `https://aislix-backend-production.up.railway.app/landing/samples/lays-a1l/image`

**Design reference:** Use the attached full-page mockup (dark navy hero, cyan accents, trusted-by strip, 3-step flow, features grid, live demo, use cases, wide lead form, footer CTA).

---

```
/retail-intelligence — FULL PROFESSIONAL LANDING PAGE (FINAL v4)

DO NOT MODIFY: "/" homepage, /signup /login /dashboard core auth, LinkedIn Insight Tag.
REBUILD COMPLETELY: /retail-intelligence and all files under src/components/landing/retail-intelligence/

══════════════════════════════════════════════════════════════
CRITICAL FIXES FROM CURRENT LIVE PAGE
══════════════════════════════════════════════════════════════

❌ Page looks like a bare internal tool — not a LinkedIn ad landing page
❌ Wrong colors (green/teal buttons) — use AISLIX BRAND PALETTE below (navy + cyan blue)
❌ Missing marketing sections from mockup — ADD ALL SECTIONS in Step 2
❌ Lead form too narrow / missing — ADD WIDE lead form (Step 7)
❌ Sample image not visible by default — FIX on mount (Step 4)
❌ Scan must use live API — keep POST /landing/scan (Step 5)

══════════════════════════════════════════════════════════════
STEP 1 — BRAND COLORS (NO GREEN)
══════════════════════════════════════════════════════════════

Create src/components/landing/retail-intelligence/landing-theme.ts:

export const landingColors = {
  navy: "#0A1628",           // hero + footer background
  navyLight: "#111D32",      // cards on dark bg
  cyan: "#00AEEF",           // primary CTA, accents, icons — AISLIX cyan blue
  cyanHover: "#0090C8",
  white: "#FFFFFF",
  gray50: "#F8FAFC",
  gray100: "#F1F5F9",
  gray600: "#475569",
  gray900: "#0F172A",
  border: "#E2E8F0",
};

RULES:
- Primary buttons: bg-[#00AEEF] hover:bg-[#0090C8] text-white — NOT emerald, NOT green-500, NOT teal-500
- Hero/footer: bg-[#0A1628] text-white
- Section alternation: white → gray-50 → white
- Icons: cyan (#00AEEF) on light cards
- Links/highlight text in hero: cyan accent on key words ("Single Photo")
- Do NOT use Tailwind green-* or emerald-* anywhere on this page
- Scan result bounding boxes come from API image — UI chrome stays navy/cyan only

Use existing AISLIX logo from site assets. Match typography: clean sans (Inter/system).

══════════════════════════════════════════════════════════════
STEP 2 — FULL PAGE STRUCTURE (match mockup — ALL sections)
══════════════════════════════════════════════════════════════

Build RetailIntelligencePage.tsx composing these sections IN ORDER:

┌──────────────────────────────────────────────────────────────┐
│ 1. LandingNav — sticky, transparent on hero → white on scroll│
│ 2. LandingHero — dark navy, headline + CTAs + mini preview   │
│ 3. TrustedByStrip — "Trusted by retail teams…" + 5 icons     │
│ 4. HowItWorks — 3 steps: Capture → Analyze → Act             │
│ 5. FeaturesGrid — 10 capability cards (2×5 grid)             │
│ 6. LiveDemoSection — id="demo" — REAL interactive scan       │
│ 7. UseCasesGrid — 5 persona cards                            │
│ 8. WideLeadForm — id="lead" — FULL WIDTH lead capture        │
│ 9. FinalCtaFooter — dark navy closing CTA + phone mockup     │
│ 10. LandingFooter — © Aislix Privacy Terms                   │
└──────────────────────────────────────────────────────────────┘

This is a FULL landing page like the mockup — NOT a stripped-down demo-only page.

──────────────────────────────────────────────────────────────
1. LandingNav
──────────────────────────────────────────────────────────────
- Sticky top, backdrop-blur when scrolled
- Left: AISLIX logo → /retail-intelligence
- Center (desktop): anchor links — How it works (#how-it-works), Features (#features), Use cases (#use-cases), Demo (#demo)
- Right: "Log in" (text) + "Start scanning free" (cyan button → scroll #demo, NOT /signup)
- Mobile: hamburger with same links

──────────────────────────────────────────────────────────────
2. LandingHero (dark navy bg #0A1628)
──────────────────────────────────────────────────────────────
Left column (lg:w-1/2):
  Eyebrow pill: "AI-Powered Retail Shelf Intelligence"
  H1: "Audit Every Aisle. From a Single Photo." — "Single Photo" in cyan
  Subhead: "Turn shelf photos into structured audits. Detect products, brands, availability and execution issues — instantly."
  CTAs:
    Primary (cyan): "Try Sample Shelf →" → scroll #demo + trigger sample scan
    Secondary (outline white): "Upload Your Photo" → scroll #demo + open file picker
  Trust row (checkmark icons, cyan):
    ✓ No card required   ✓ 3 free scans per day   ✓ Results in ~60 seconds

Right column (lg:w-1/2):
  Show a polished PREVIEW CARD (not empty):
  - Thumbnail of sample Lay's rack (DEFAULT_SAMPLE_IMAGE URL)
  - Mini stat chips overlay: "Products detected", "Unique SKUs", "Shelf health"
  - Subtle glow border cyan/20 — looks like product screenshot from mockup
  - On click → scroll to #demo

──────────────────────────────────────────────────────────────
3. TrustedByStrip (white bg, py-12)
──────────────────────────────────────────────────────────────
  Text: "Trusted by retail teams across modern trade, dark stores and field operations"
  5 icon+label columns: Supermarkets | Dark Stores | FMCG Brands | Distributors | Local Stores
  Use lucide icons (Store, Warehouse, Building2, Truck, ShoppingBag) in gray-400

──────────────────────────────────────────────────────────────
4. HowItWorks — id="how-it-works" (gray-50 bg)
──────────────────────────────────────────────────────────────
  H2: "From Shelf Photo to Action in 3 Simple Steps"
  3 columns with dashed connector line (desktop):
    01 Capture — smartphone icon — "Take a shelf photo using any smartphone."
    02 Analyze — sparkles icon — "Aislix AI detects products, brands, quantities and shelf issues."
    03 Act — bar-chart icon — "Get insights and fix execution gaps faster."
  Number badges in cyan circles

──────────────────────────────────────────────────────────────
5. FeaturesGrid — id="features" (white bg)
──────────────────────────────────────────────────────────────
  H2: "One Photo. Multiple Layers of Intelligence."
  10 cards (grid grid-cols-1 sm:2 lg:5 gap-4):
    Product Detection | SKU Recognition | Brand Recognition | Out-of-Stock Detection
    Shelf Position | Product Count | Planogram Compliance | Shelf Health Score
    Low Stock Alerts | Retail Execution
  Each: cyan icon top-left, title bold, one-line description gray-600
  Card: white border border-gray-200 rounded-xl p-5 hover:shadow-md transition

──────────────────────────────────────────────────────────────
6. LiveDemoSection — id="demo" (gray-50 bg) ★ CORE PRODUCT
──────────────────────────────────────────────────────────────
  Eyebrow: "LIVE DEMO"
  H2: "See What Aislix Sees"
  Sub: "Upload a shelf photo and watch AI turn it into structured retail intelligence."

  Control bar:
    [Try Sample Shelf] — cyan filled, default active
    [Upload Shelf Photo] — outline navy
    Helper: "JPEG or PNG, up to 10MB • No login required"

  Demo card (white, rounded-2xl, shadow-xl, p-6):
    2-column layout desktop (55% / 45%):

    LEFT — Shelf image panel:
      Label: "Shelf image" + badge "AI annotated" when done
      ON MOUNT: set previewImageUrl = DEFAULT_SAMPLE_IMAGE (see Step 4)
      Always show <img> when previewImageUrl set — NEVER empty placeholder
      While scanning: keep image + pulsing cyan overlay "Analyzing shelf…"
      When done: show annotated_image_base64 from API

    RIGHT — Results panel:
      Idle (before scan): show 3 gray metric placeholders + text "Click Try Sample Shelf to run live AI analysis"
      Scanning: cyan spinner + "Analyzing shelf… 30–90s" + progress subtext
      Done: 3 metric cards (Products detected, Unique SKUs, Shelf health)
             executive_summary paragraph
             table: Brand | Product | Qty | Conf. | Status
             status_label: Detected | Needs review — NO planogram/compliance columns
             "{used} of {limit} free demo scans used today"
             [Download CSV] outline button with Download icon

  Below demo card (centered):
    Cyan link: "Save this audit — scroll to get your free scans ↓" → #lead

──────────────────────────────────────────────────────────────
7. UseCasesGrid — id="use-cases" (white bg)
──────────────────────────────────────────────────────────────
  H2: "Built for Every Retail Team"
  5 cards: Retail Operations | FMCG & Brands | Field Sales | Category Management | Merchandising Teams
  Icon + title + 2-line description each

──────────────────────────────────────────────────────────────
8. WideLeadForm — id="lead" (gray-50 bg) ★ LEAD GENERATION
──────────────────────────────────────────────────────────────
  Full-width section, max-w-5xl mx-auto (NOT max-w-xl — WIDE FORM)

  White card, rounded-2xl, shadow-lg, p-10 lg:p-14:

  Left column (lg:w-2/5):
    Eyebrow cyan: "Get started free"
    H2: "Save your shelf audit & unlock 3 free scans"
    Bullets with cyan checks:
      ✓ Instant AI shelf analysis
      ✓ CSV export included
      ✓ No credit card required

  Right column (lg:w-3/5) — WIDE FORM:
    Grid grid-cols-1 md:grid-cols-2 gap-4:
      Row 1: Full name (input) | Work email * (input, required)
      Row 2: Company (input, md:col-span-2)
      Row 3: Role dropdown optional (Retail Ops / FMCG / Field Sales / Other)
    Full-width cyan button: "Continue →"
      → captureLandingLead({ landing_session_id, email, name, company })
      → on success show: "You're all set!" + [Create Free Account →] signupUrlWithLanding()
    Small text: "By continuing you agree to our Terms. Already have an account? Log in"

  If no scan yet: form still visible but show hint "Run a demo scan above to attach your audit results"

──────────────────────────────────────────────────────────────
9. FinalCtaFooter (dark navy #0A1628)
──────────────────────────────────────────────────────────────
  Split layout like mockup:
  Left:
    H2 white: "Ready to See What Your Shelves Are Telling You?"
    Sub gray-300: "Start with 3 free shelf scans. No credit card required."
    Buttons: cyan "Start free shelf scan →" (scroll #demo) + outline "Get your results" (scroll #lead)
    Trust: Instant results • No setup needed • Cancel anytime
  Right: phone/device mockup frame showing sample annotated shelf (use last scan result or DEFAULT_SAMPLE_IMAGE)

──────────────────────────────────────────────────────────────
10. LandingFooter
──────────────────────────────────────────────────────────────
  Simple: © 2026 Aislix • Privacy • Terms
  Dark bg or gray-900, small text

══════════════════════════════════════════════════════════════
STEP 3 — API CLIENT (src/lib/landing-scan-api.ts)
══════════════════════════════════════════════════════════════

const API = import.meta.env.VITE_AISLIX_API_URL;

export const DEFAULT_SAMPLE_ID = "lays-a1l";
export const DEFAULT_SAMPLE_IMAGE = `${API}/landing/samples/${DEFAULT_SAMPLE_ID}/image`;

export type LandingScanResult = {
  landing_session_id: string;
  scan_id: string;
  status: "completed";
  metrics: { total_products?: number; unique_skus?: number; shelf_health_score?: number };
  inventory: Array<{ brand: string; product_name: string; quantity: number; confidence?: number; status_label?: string }>;
  executive_summary?: string;
  annotated_image_base64?: string;
  annotated_image_mime?: string;
  original_image_base64?: string;
  csv_base64?: string;
  scans_used_today?: number;
  scans_daily_limit?: number;
};

function appendUtm(form: FormData) {
  const p = new URLSearchParams(window.location.search);
  for (const k of ["utm_source","utm_medium","utm_campaign","utm_content","utm_term"]) {
    const v = p.get(k); if (v) form.append(k, v);
  }
}

export async function runLandingSample(sampleId = DEFAULT_SAMPLE_ID, sid?: string): Promise<LandingScanResult> {
  const form = new FormData();
  form.append("sample_id", sampleId);
  if (sid) form.append("landing_session_id", sid);
  appendUtm(form);
  const res = await fetch(`${API}/landing/scan`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json().catch(()=>({}))).detail || "Scan failed");
  return res.json();
}

export async function runLandingUpload(file: File, sid?: string): Promise<LandingScanResult> {
  const form = new FormData();
  form.append("file", file);
  if (sid) form.append("landing_session_id", sid);
  appendUtm(form);
  const res = await fetch(`${API}/landing/scan`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json().catch(()=>({}))).detail || "Scan failed");
  return res.json();
}

export async function captureLandingLead(payload: {
  landing_session_id: string; email: string; name?: string; company?: string;
}) {
  await fetch(`${API}/landing/lead`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function convertLandingSession(sid: string, userId: string) {
  await fetch(`${API}/landing/convert`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ landing_session_id: sid, user_id: userId }),
  });
}

export function persistLandingSession(r: LandingScanResult) {
  sessionStorage.setItem("aislix_landing_session_id", r.landing_session_id);
  sessionStorage.setItem("aislix_landing_scan_result", JSON.stringify(r));
}

export function loadLandingSessionId() {
  return sessionStorage.getItem("aislix_landing_session_id");
}

export function signupUrlWithLanding() {
  const p = new URLSearchParams(window.location.search);
  const sid = loadLandingSessionId();
  if (sid) p.set("landing_session_id", sid);
  const qs = p.toString();
  return qs ? `/signup?${qs}` : "/signup";
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

══════════════════════════════════════════════════════════════
STEP 4 — DEFAULT SAMPLE IMAGE (on mount — CRITICAL)
══════════════════════════════════════════════════════════════

In LiveDemoSection AND LandingHero preview:

useEffect(() => {
  setPreviewImageUrl(DEFAULT_SAMPLE_IMAGE);
}, []);

Left demo panel MUST show Lay's rack image immediately on page load.
Never show "Your shelf photo appears here" when previewImageUrl is set.

══════════════════════════════════════════════════════════════
STEP 5 — SCAN BEHAVIOUR
══════════════════════════════════════════════════════════════

"Try Sample Shelf":
  1. setPhase("scanning") — keep previewImageUrl visible
  2. result = await runLandingSample()
  3. persistLandingSession(result)
  4. setPhase("done"); show annotated image + table
  5. setTimeout(() => document.getElementById("lead")?.scrollIntoView({ behavior: "smooth" }), 1200)

"Upload Shelf Photo":
  1. File pick → setPreviewImageUrl(URL.createObjectURL(file)) immediately
  2. runLandingUpload(file) → same flow

Hero "Try Sample Shelf" → scrollTo(#demo) then trigger same handler.

All CTAs "Start scanning free" / "Start free shelf scan" → scroll #demo (NOT /signup before scan).

══════════════════════════════════════════════════════════════
STEP 6 — SIGNUP CONVERSION (/signup minimal hook)
══════════════════════════════════════════════════════════════

After signUp + user.id:
  if (landing_session_id from URL or sessionStorage) convertLandingSession(sid, user.id)

══════════════════════════════════════════════════════════════
STEP 7 — COMPONENT FILE STRUCTURE
══════════════════════════════════════════════════════════════

src/pages/RetailIntelligencePage.tsx
src/components/landing/retail-intelligence/
  LandingNav.tsx
  LandingHero.tsx
  TrustedByStrip.tsx
  HowItWorks.tsx
  FeaturesGrid.tsx
  LiveDemoSection.tsx      ← scan logic lives here
  UseCasesGrid.tsx
  WideLeadForm.tsx         ← wide 2-column form
  FinalCtaFooter.tsx
  LandingFooter.tsx
  landing-theme.ts
src/lib/landing-scan-api.ts

══════════════════════════════════════════════════════════════
STEP 8 — QA BEFORE PUBLISH
══════════════════════════════════════════════════════════════

✓ Full landing page with ALL 10 sections (looks like mockup)
✓ Colors: navy hero/footer + cyan (#00AEEF) CTAs — ZERO green Tailwind classes
✓ Sample Lay's image visible on load in demo + hero preview
✓ Live scan works via POST /landing/scan
✓ Wide lead form (max-w-5xl, 2-column inputs)
✓ Download CSV works
✓ No "On planogram" in results table
✓ / homepage unchanged
✓ LinkedIn Insight Tag preserved
✓ Mobile responsive — sections stack cleanly

Publish to production when QA passes.
```
