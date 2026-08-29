# Lovable Prompt — `/retail-shelf-intelligence` (v5 — final revisions)

Paste this **entire block** into Lovable chat → **Publish** to `https://aislix.com/retail-shelf-intelligence`.

**Backend API:** `https://aislix-backend-production.up.railway.app`  
**Env:** `VITE_AISLIX_API_URL=https://aislix-backend-production.up.railway.app`  
**Default sample image (shampoo shelf — fast scan):**  
`https://aislix-backend-production.up.railway.app/landing/samples/shampoo-a1z/image`

---

```
/retail-shelf-intelligence — LANDING PAGE v5 (apply ALL changes below)

DO NOT MODIFY: "/" homepage content, /signup /login /dashboard core flows, LinkedIn Insight Tag.
CREATE/UPDATE ONLY: /retail-shelf-intelligence + src/components/landing/retail-shelf-intelligence/

══════════════════════════════════════════════════════════════
MANDATORY CHANGES (user requirements)
══════════════════════════════════════════════════════════════

1. COLORS — use ONLY existing AISLIX website brand colors
   ❌ Remove ALL sky blue, cyan (#00AEEF), cyan-400/500, teal, emerald, green accents
   ✅ Reuse exact classes/tokens from homepage: primary Button variant, text-primary,
      bg-primary, border-primary, existing tailwind.config theme colors
   ✅ Import/reuse SiteHeader, Button, Card from existing components — do NOT invent new palette
   ✅ Hero/footer dark navy ONLY if that matches homepage header — otherwise match homepage exactly

2. HERO CTA — single big button only
   ❌ REMOVE "View live demo" button entirely (hero, nav, footer — everywhere)
   ✅ ONE primary hero button (large, full brand primary color):
      "Start scanning free →"
      onClick → smooth scroll to #demo ("See What Aislix Sees" section)
      NOT /signup from hero — demo first, signup after lead form

3. SAMPLE IMAGE — shampoo (NOT Lay's — too slow)
   ✅ Default sample_id: "shampoo-a1z"
   ✅ Preview URL on mount:
      `${VITE_AISLIX_API_URL}/landing/samples/shampoo-a1z/image`
   ✅ "Try Sample Shelf" → POST /landing/scan with sample_id=shampoo-a1z
   ✅ Shampoo photo visible immediately on page load in demo left panel

4. LEAD FORM — directly below live demo
   ✅ WideLeadCapture section IMMEDIATELY after LiveDemoSection (no sections between)
   ❌ REMOVE duplicate "See What Aislix Sees" / ProductShowcase section entirely

5. TOP NAV — same links as homepage ONLY
   ✅ Reuse <SiteHeader /> from src/components/MarketingLayout.tsx (or copy exact same links)
   Homepage nav links (from existing site):
     Platform → /platform (or #platform on / if that's how homepage works)
     How it works → /#how or anchor used on homepage
     Pricing → /pricing
     Contact → /contact
     About → /about
     Sign in → /login
     Start free → /signup (with UTMs preserved)
   ❌ Do NOT use landing-only nav (How it works / Features / Use cases / Demo anchors)
   ❌ Do NOT invent new nav items

══════════════════════════════════════════════════════════════
PAGE SECTION ORDER
══════════════════════════════════════════════════════════════

1.  SiteHeader (homepage nav — reused component)
2.  LandingHero
3.  TrustBar ("Built for modern retail teams")
4.  ProblemSection
5.  HowItWorks — id="how-it-works"
6.  FeaturesGrid — id="features"
7.  LiveDemoSection — id="demo" ★ "See What Aislix Sees"
8.  WideLeadCapture — id="lead" ★ directly below demo
9.  UseCasesGrid — id="use-cases"
10. RoiSection
11. FaqSection — id="faq"
12. FinalCtaSection (dark — match homepage footer CTA style)
13. LandingFooter (match homepage footer links)

NO ProductShowcase section. NO second "See What Aislix Sees".

══════════════════════════════════════════════════════════════
HERO SECTION
══════════════════════════════════════════════════════════════

Badge: "AI-Powered Retail Shelf Intelligence"
H1: "Audit Every Aisle. From a Single Photo." — emphasize second line with text-primary (brand color, NOT sky blue)
Subhead: "Aislix turns a single shelf photo into a complete retail audit — products detected, brands counted, out-of-stocks flagged and shelf health scored."

ONE CTA only (large, brand primary Button):
  "Start scanning free →" → scrollIntoView(#demo)

Trust row: ✓ No card required  ✓ 3 free scans per day  ✓ Results in seconds

Right side: product preview card showing shampoo sample image + placeholder metric chips.
Use DEFAULT_SAMPLE_IMAGE URL for thumbnail.

══════════════════════════════════════════════════════════════
LIVE DEMO — id="demo"
══════════════════════════════════════════════════════════════

Eyebrow: "LIVE DEMO"
H2: "See What Aislix Sees"
Sub: "Try a real shelf scan — no login required."

src/lib/landing-scan-api.ts:

const API = import.meta.env.VITE_AISLIX_API_URL;
export const DEFAULT_SAMPLE_ID = "shampoo-a1z";
export const DEFAULT_SAMPLE_IMAGE = `${API}/landing/samples/${DEFAULT_SAMPLE_ID}/image`;

Implement: runLandingSample(), runLandingUpload(), captureLandingLead(),
convertLandingSession(), persistLandingSession(), downloadLandingCsv(), signupUrl()

POST /landing/scan — sample_id=shampoo-a1z OR file upload
GET  /landing/samples/shampoo-a1z/image

ON MOUNT:
  setPreviewImageUrl(DEFAULT_SAMPLE_IMAGE);
  Shampoo shelf MUST be visible immediately — never empty placeholder.

Controls (brand primary + outline buttons — existing Button component):
  [Try Sample Shelf] — runs live scan (shampoo-a1z)
  [Upload Shelf Photo] — file upload

Layout: 2 columns — left shelf image (always visible, analyzing overlay while waiting),
right results panel (metrics, table, Download CSV).

Table columns: Brand | Product | Qty | Conf. | Status
NO planogram/compliance columns. Use status_label from API.

After scan completes: optional soft scroll to #lead (lead form is right below).

══════════════════════════════════════════════════════════════
LEAD CAPTURE — id="lead" (IMMEDIATELY below #demo) — FIX SUBMIT ERROR
══════════════════════════════════════════════════════════════

Title: "Get Your Free Shelf Intelligence Access"
Sub: "Enter your work email to start scanning. No credit card required."

Form grid (2x2):
  Work email * | Full name
  Company      | Role

Submit button (brand primary, full width):
  "Get more free scans"

On submit — call captureLandingLead():

export async function captureLandingLead(payload: {
  landing_session_id?: string;
  email: string;
  name?: string;
  company?: string;
  role?: string;
}) {
  const sid = payload.landing_session_id || sessionStorage.getItem("aislix_landing_session_id") || undefined;
  const p = new URLSearchParams(window.location.search);
  const body: Record<string, string | undefined> = { ...payload, landing_session_id: sid };
  for (const k of ["utm_source","utm_medium","utm_campaign","utm_content","utm_term"]) {
    const v = p.get(k);
    if (v) body[k] = v;
  }
  const res = await fetch(`${API}/landing/lead`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "Could not save your details.");
  if (data.landing_session_id) sessionStorage.setItem("aislix_landing_session_id", data.landing_session_id);
  return data;
}

SUCCESS STATE (replace form — do NOT show error if data.ok === true):

  ✉️ icon
  H3: "Check your email"
  Body: "We sent onboarding instructions to {email}. Open the email and click the link to create your free Aislix workspace and unlock 3 shelf scans."
  Small: "Didn't receive it? Check spam or wait a minute."

  Optional fallback link: "Continue to signup →" signupUrl()

ERROR STATE only when res.ok === false OR thrown exception.

❌ Do NOT show "Could not save your details" when API returns ok: true
❌ landing_session_id is OPTIONAL — backend creates session if missing

Pre-fill /signup from email link: /signup?email=...&landing_session_id=...

══════════════════════════════════════════════════════════════
RAILWAY ENV (backend — already deployed after push)
══════════════════════════════════════════════════════════════

Set on Railway:
  RESEND_API_KEY=...          (same key as Lovable edge functions)
  LANDING_FROM_EMAIL=Aislix <onboarding@aislix.com>  (or verified Resend sender)
  APP_ORIGIN=https://aislix.com

Run Supabase SQL: supabase/migrations/20260829180000_landing_lead_onboarding_email.sql

══════════════════════════════════════════════════════════════
OTHER SECTIONS (keep from v4 — use brand colors only)
══════════════════════════════════════════════════════════════

TrustBar, ProblemSection, HowItWorks, FeaturesGrid, UseCasesGrid, RoiSection, FaqSection,
FinalCtaSection, LandingFooter — content unchanged from prior prompt but:
- All buttons use existing primary Button (no sky blue)
- Final CTA "Start free shelf scan →" → signupUrl() (this one CAN go to /signup)
- Repeat signupUrl() CTAs after Features grid and Final CTA section

══════════════════════════════════════════════════════════════
SIGNUP ATTRIBUTION (/signup minimal hook)
══════════════════════════════════════════════════════════════

signupUrl() preserves utm_* + landing_session_id from sessionStorage.
After signUp: POST /landing/convert { landing_session_id, user_id }

══════════════════════════════════════════════════════════════
QA CHECKLIST
══════════════════════════════════════════════════════════════

✓ Nav matches homepage exactly (Platform, How it works, Pricing, Contact, About)
✓ NO sky blue / cyan / teal anywhere — only existing brand colors
✓ NO "View live demo" button anywhere
✓ Hero "Start scanning free" scrolls to #demo
✓ Shampoo image visible on load; Try Sample Shelf uses shampoo-a1z (faster than Lay's)
✓ Lead form directly under demo — NO duplicate See What Aislix Sees section
✓ Live scan + CSV download work
✓ / homepage unchanged

Publish when complete.
```
