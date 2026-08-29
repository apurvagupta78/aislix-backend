# Lovable Prompt — LinkedIn Ads Landing Page `/retail-intelligence` (Live Scan + Lead Capture)

Paste this entire prompt into Lovable chat, then **Publish** to production (`https://aislix.com`).

**Prerequisite — run in Lovable Cloud SQL first:**
`supabase/migrations/20260829140000_landing_demo_sessions.sql`

Also create Supabase Storage bucket **`landing-scans`** (private). Backend uploads via service role.

**Backend API (Railway):** `https://aislix-backend-production.up.railway.app`

---

```
RETAIL INTELLIGENCE LANDING — FIX LIVE DEMO + LEAD FUNNEL

CRITICAL — DO NOT MODIFY:
- src/routes/index.tsx (homepage "/") — leave 100% unchanged
- /signup, /login, /dashboard core auth flows
- Existing scan pipeline for logged-in users
- LinkedIn Insight Tag — preserve exactly

ONLY CHANGE:
- /retail-intelligence page and its components under src/components/landing/retail-intelligence/
- Add src/lib/landing-scan-api.ts (new)
- Optional: src/lib/landing-analytics.ts, src/lib/utm.ts

══════════════════════════════════════════════════════════════
PROBLEM TO FIX (current page is wrong)
══════════════════════════════════════════════════════════════

1. CTAs force /signup BEFORE the user can scan — WRONG
2. Demo uses STATIC Lay's data overlaid on WRONG images (e.g. shampoo shelf) — WRONG
3. User must scan anonymously FIRST, see REAL AI results, THEN give details/sign up

══════════════════════════════════════════════════════════════
TARGET FUNNEL
══════════════════════════════════════════════════════════════

LinkedIn Ad
  → /retail-intelligence?utm_source=linkedin&...
  → user uploads shelf photo OR tries matched sample
  → LIVE AI scan (no login)
  → real annotated image + inventory table
  → lead form: email (+ optional name, company)
  → "Create free account" → /signup?landing_session_id=...&utm_...
  → after signup: POST /landing/convert with user_id
  → /dashboard

Backend stores: session, image, scan result, UTM, lead email, whether user signed up.

══════════════════════════════════════════════════════════════
STEP 0 — ENV
══════════════════════════════════════════════════════════════

Add to .env (or Lovable env vars):

  VITE_AISLIX_API_URL=https://aislix-backend-production.up.railway.app

Use import.meta.env.VITE_AISLIX_API_URL in frontend code.

══════════════════════════════════════════════════════════════
STEP 1 — API CLIENT (src/lib/landing-scan-api.ts)
══════════════════════════════════════════════════════════════

const API = import.meta.env.VITE_AISLIX_API_URL;

export type LandingScanResult = {
  landing_session_id: string;
  scan_id: string;
  status: "completed";
  metrics: {
    total_products?: number;
    unique_skus?: number;
    shelf_health_score?: number;
    needs_review_facings?: number;
  };
  inventory: Array<{
    brand: string;
    product_name: string;
    quantity: number;
    confidence?: number;
    compliance_status?: string;
    counted_in_totals?: boolean;
    exclusion_reason?: string;
  }>;
  executive_summary?: string;
  annotated_image_base64?: string;
  annotated_image_mime?: string;
  facings_debug?: Array<{ x1: number; y1: number; x2: number; y2: number; brand?: string; product_name?: string; confidence?: number }>;
  scans_used_today?: number;
  scans_daily_limit?: number;
};

function appendUtm(form: FormData) {
  const params = new URLSearchParams(window.location.search);
  for (const key of ["utm_source","utm_medium","utm_campaign","utm_content","utm_term"]) {
    const v = params.get(key);
    if (v) form.append(key, v);
  }
}

export async function runLandingScan(file: File, landingSessionId?: string): Promise<LandingScanResult> {
  const form = new FormData();
  form.append("file", file);
  if (landingSessionId) form.append("landing_session_id", landingSessionId);
  appendUtm(form);
  const res = await fetch(`${API}/landing/scan`, { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Scan failed (${res.status})`);
  }
  return res.json();
}

export async function runLandingSample(sampleId = "lays-a1l", landingSessionId?: string): Promise<LandingScanResult> {
  const form = new FormData();
  form.append("sample_id", sampleId);
  if (landingSessionId) form.append("landing_session_id", landingSessionId);
  appendUtm(form);
  const res = await fetch(`${API}/landing/scan`, { method: "POST", body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Sample scan failed (${res.status})`);
  }
  return res.json();
}

export async function captureLandingLead(payload: {
  landing_session_id: string;
  email: string;
  name?: string;
  company?: string;
  phone?: string;
}) {
  const res = await fetch(`${API}/landing/lead`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Could not save lead");
  return res.json();
}

export async function convertLandingSession(landingSessionId: string, userId: string) {
  await fetch(`${API}/landing/convert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ landing_session_id: landingSessionId, user_id: userId }),
  });
}

export function persistLandingSession(result: LandingScanResult) {
  sessionStorage.setItem("aislix_landing_session_id", result.landing_session_id);
  sessionStorage.setItem("aislix_landing_scan_result", JSON.stringify(result));
}

export function loadLandingSessionId(): string | null {
  return sessionStorage.getItem("aislix_landing_session_id");
}

export function signupUrlWithLanding(): string {
  const params = new URLSearchParams(window.location.search);
  const sid = loadLandingSessionId();
  if (sid) params.set("landing_session_id", sid);
  const qs = params.toString();
  return qs ? `/signup?${qs}` : "/signup";
}

══════════════════════════════════════════════════════════════
STEP 2 — HERO CTAs (no signup before scan)
══════════════════════════════════════════════════════════════

Primary CTA: "Analyze a Shelf Photo"
  → scroll to #demo AND focus upload area (do NOT link to /signup)

Secondary CTA: "See How Aislix Works"
  → scroll to #how-it-works

Header CTA "Start Free Shelf Scan":
  → ONLY after user has completed one scan, scroll to lead gate OR go to signupWithUtm()
  → BEFORE first scan: same as primary — scroll to #demo

Trust line: "3 free shelf scans • No credit card required"

REMOVE any hero button that goes directly to /signup before scan.

══════════════════════════════════════════════════════════════
STEP 3 — INTERACTIVE DEMO (id="demo") — LIVE SCAN
══════════════════════════════════════════════════════════════

H2: See What Aislix Sees
Subhead: Upload a shelf photo and see how AI turns it into structured retail intelligence.

Two tabs/buttons:
  A) "Try Sample Shelf" — calls runLandingSample("lays-a1l")
     IMPORTANT: sample uses backend reference Lay's rack image — results WILL match Lay's chips.
     Do NOT show sample Lay's bounding boxes on user-uploaded images.
  B) "Upload Shelf Photo" — file input (jpeg/png, max 10MB)

States:
  idle → scanning (spinner, "Analyzing shelf… 30–90s") → results | error

On success:
  - persistLandingSession(result)
  - Left: show annotated image from API:
      src={`data:${result.annotated_image_mime};base64,${result.annotated_image_base64}`}
    Do NOT draw fake CSS boxes from static data.
  - Right: metrics from result.metrics:
      Products detected → metrics.total_products
      Unique SKUs → metrics.unique_skus
      Shelf health → metrics.shelf_health_score
  - Table from result.inventory (same columns as dashboard scan results):
      Brand | Product | Qty | Conf. | Compliance
      Show "Needs review" badge when compliance_status === "needs_review"
      Gray out / badge rows where counted_in_totals === false

On error:
  - Friendly message; if 429 (daily limit) show "Sign up for unlimited scans" CTA

DO NOT use hardcoded landingDemoSample.ts for live uploads.
DELETE or stop using static overlay data for user uploads.

══════════════════════════════════════════════════════════════
STEP 4 — LEAD GATE (after results, BEFORE signup pressure)
══════════════════════════════════════════════════════════════

After scan results appear, show inline card (same #demo section, below results):

  Headline: "Save your results & analyze more shelves"
  Subtext: "Enter your work email to unlock 3 free shelf scans in your workspace."

  Form fields:
    - Email (required)
    - Name (optional)
    - Company (optional)

  Button: "Continue" → on submit:
    1. captureLandingLead({ landing_session_id, email, name, company })
    2. track event landing_lead_captured
    3. reveal second step OR redirect:

  Second step CTA: "Create Free Account →"
    → signupUrlWithLanding()  (preserves UTM + landing_session_id)

Optional skip link (small text): "Continue without saving" → signupUrlWithLanding()

DO NOT block viewing results behind the form — results are visible first, form is below.

══════════════════════════════════════════════════════════════
STEP 5 — SIGNUP CONVERSION HOOK
══════════════════════════════════════════════════════════════

On /signup page (minimal additive change only):

  - Read landing_session_id from query string OR sessionStorage
  - After successful signUp + user.id available:
      await convertLandingSession(landingSessionId, user.id)
  - Pass landing_session_id in signUp metadata if you use Supabase raw_user_meta_data:
      options: { data: { landing_session_id: sid } }

On /auth/callback or post-login bootstrap (if exists):
  - If landing_session_id in sessionStorage and user logged in → convertLandingSession

This links anonymous demo → registered user in backend DB.

══════════════════════════════════════════════════════════════
STEP 6 — UTM PRESERVATION
══════════════════════════════════════════════════════════════

src/lib/utm.ts — on /retail-intelligence mount:
  - Parse utm_* from URL → sessionStorage
  - signupUrlWithLanding() merges UTMs + landing_session_id

LinkedIn Insight Tag: fire on page view + landing_scan_completed + landing_lead_captured

══════════════════════════════════════════════════════════════
STEP 7 — NAV / REST OF PAGE
══════════════════════════════════════════════════════════════

Keep existing sections (#how-it-works, #capabilities, #use-cases, footer).
Logo links to /retail-intelligence (not /).

Final footer CTA: signupUrlWithLanding() — "Start Free Shelf Scan"

Mobile: sticky bottom bar "Analyze a Shelf Photo" → #demo (not /signup)

══════════════════════════════════════════════════════════════
STEP 8 — ANALYTICS EVENTS
══════════════════════════════════════════════════════════════

trackLandingEvent(name, props):
  - landing_page_view
  - demo_scan_started { mode: "sample" | "upload" }
  - demo_scan_completed { scan_id, landing_session_id, products: metrics.total_products }
  - demo_scan_failed { error }
  - landing_lead_captured { landing_session_id }
  - cta_click { location: "hero" | "demo" | "footer" | "lead_gate" }

══════════════════════════════════════════════════════════════
STEP 9 — QA CHECKLIST
══════════════════════════════════════════════════════════════

✓ / unchanged
✓ /retail-intelligence loads without login
✓ "Analyze a Shelf Photo" does NOT go to /signup
✓ Upload image → real API call → annotated image matches products in table
✓ "Try Sample Shelf" → Lay's rack image + Lay's products (not shampoo labels on chips)
✓ Results visible before email form
✓ Email submit hits POST /landing/lead
✓ Signup URL includes landing_session_id + UTMs
✓ After signup, POST /landing/convert fires
✓ 429 shows friendly limit message

══════════════════════════════════════════════════════════════
BACKEND ENDPOINTS (already deployed on Railway after backend push)
══════════════════════════════════════════════════════════════

POST /landing/scan          multipart: file OR sample_id, utm_*, landing_session_id
GET  /landing/session/:id   reload session metadata (no image — use sessionStorage for full result)
POST /landing/lead          JSON: landing_session_id, email, name?, company?, phone?
POST /landing/convert       JSON: landing_session_id, user_id
GET  /landing/samples       list available sample_id values

Rate limit: 5 anonymous scans per IP per day (env LANDING_SCAN_DAILY_LIMIT).

══════════════════════════════════════════════════════════════
ADMIN / REPORTING (Supabase SQL)
══════════════════════════════════════════════════════════════

-- All landing scans
SELECT session_token, created_at, utm_source, utm_campaign, scan_status,
       lead_email, signup_completed, converted_user_id
FROM landing_demo_sessions
ORDER BY created_at DESC;

-- Conversion rate
SELECT
  COUNT(*) FILTER (WHERE scan_status = 'completed') AS scans,
  COUNT(*) FILTER (WHERE lead_email IS NOT NULL) AS leads,
  COUNT(*) FILTER (WHERE signup_completed) AS signups
FROM landing_demo_sessions;

Publish when QA passes.
```
