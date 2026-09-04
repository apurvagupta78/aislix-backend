# Lovable Prompt — Homepage Hero + Live Demo Dashboard + Lead Form

Paste this **entire block** into Lovable chat → **Publish** to `https://aislix.com/`.

**Reference:** Attached screenshot — hero with shampoo shelf product card, navy CTAs, trust pills.

**Env (if live demo uses API later):** `VITE_AISLIX_API_URL=https://aislix-backend-production.up.railway.app`

---

```
HOMEPAGE (/) — ADD HERO + LIVE DEMO + LEAD FORM (reorder sections only)

DO NOT MODIFY: /signup, /login, /dashboard app routes, auth, Supabase, existing footer content beyond reorder.
DO NOT break existing homepage sections — INSERT and REORDER only as specified below.

USE ONLY existing AISLIX brand colors (primary Button, text-primary, bg-primary from tailwind config).
NO sky blue / cyan / emerald accent colors.

══════════════════════════════════════════════════════════════
NEW HOMEPAGE SECTION ORDER
══════════════════════════════════════════════════════════════

Keep everything that already exists on /, but ensure this order:

1.  SiteHeader (unchanged)
2.  … existing homepage content ABOVE the dashboard (if any) — unchanged
3.  ★ NEW: HomeScanHero — id="start-scanning" (attached screenshot)
4.  ★ EXISTING: current dashboard / product preview section — UNCHANGED, keep as-is
5.  ★ NEW or MOVED: HomeLeadCapture — id="lead" (lead generation form)
6.  … all remaining homepage sections below (how it works, features, pricing, etc.) — UNCHANGED

If dashboard section already exists with an id, reuse it (e.g. #dashboard or #platform).
Insert HomeScanHero immediately BEFORE that section.
Insert HomeLeadCapture immediately AFTER that section.

══════════════════════════════════════════════════════════════
SECTION A — HomeScanHero (match attached screenshot exactly)
══════════════════════════════════════════════════════════════

Create: src/components/home/HomeScanHero.tsx

Layout: two columns desktop, stacked mobile. Light/white page background (match homepage).

LEFT COLUMN:
  Badge pill (white border, subtle shadow):
    "AI-Powered Retail Shelf Intelligence"

  H1 (bold, dark):
    "Audit Every Aisle.
    From a Single Photo."

  Subhead (gray):
    "Aislix turns a single shelf photo into a complete retail audit — products detected, brands counted, out-of-stocks flagged and shelf health scored."

  TWO buttons side by side (desktop), stacked mobile:
    1. Primary (navy, existing Button variant):
       "Start scanning free →"
       → smooth scroll to #lead (lead form below dashboard)
       OR signupUrl() if you prefer direct signup — use scroll #lead for this task

    2. Secondary (outline):
       "Live demo"
       → onClick: setShowLiveDemo(true) OR scroll to #live-demo-dashboard
       Opens/shows full dashboard preview with dummy data (Section B)

  Trust row (checkmark icons):
    ✓ No card required
    ✓ 3 free scans per day
    ✓ Results in seconds

RIGHT COLUMN — product preview card (white, rounded-2xl, shadow, border):
  Split card like screenshot:

  LEFT half — label "SHELF PHOTO" (small caps gray):
    Use toothpaste shelf image (default homepage / demo sample):
    https://aislix-backend-production.up.railway.app/landing/samples/toothpaste-a1l/image
    (sample_id: toothpaste-a1l — see docs/LOVABLE_HOMEPAGE_SCAN_UX_PROMPT.md)

  RIGHT half — label "AI ANALYSIS" (small caps gray):
    Dummy metrics (match screenshot style):
      8 Products
      4 Out of stock
      91% Shelf health

    "TOP ISSUES DETECTED" (small blue/navy label — use text-primary NOT sky blue):
      • Out of stock
      • Wrong placement
      • Low stock
      • Planogram break

  Below hero (full width): "Built for modern retail teams" + 5 icon columns:
    Supermarkets | Dark Stores | FMCG Brands | Distributors | Local Stores
    (reuse TrustBar from landing if it exists, or inline here)

══════════════════════════════════════════════════════════════
SECTION B — Live Demo Dashboard (dummy data)
══════════════════════════════════════════════════════════════

Create: src/components/home/HomeLiveDemoDashboard.tsx
id="live-demo-dashboard"

Shown when user clicks "Live demo" OR always visible as expandable panel below hero.
Preferred: clicking "Live demo" scrolls here and expands section (not a separate route).

Build a COMPLETE dashboard preview using EXISTING dashboard/scan-results UI components
(styled like logged-in scan results — reuse ScanResults, metrics cards, inventory table if available).

ALL DATA IS STATIC DUMMY — no API call required for Live demo on homepage:

  Metrics row:
    Products detected: 31
    Unique SKUs: 8
    Shelf health: 91
    Out of stock: 4

  Left: annotated shelf image (shampoo sample URL above) with subtle overlay badge "Demo data"

  Right: full results panel:
    Executive summary paragraph (dummy):
      "This shelf audit detected 31 product facings across 8 unique SKUs. Shelf utilization is 78% with average AI confidence of 89%."

    Inventory table (dummy rows):
      Head & Shoulders | Cool Menthol Shampoo | 3 | 92% | Detected
      Dove | Intense Repair Shampoo | 2 | 88% | Detected
      Tresemme | Keratin Smooth Shampoo | 2 | 85% | Detected
      L'Oreal | Hyaluron Moisture Shampoo | 1 | 90% | Detected
      Pantene | Daily Moisture Renewal | 2 | 87% | Detected
      Unknown | Unidentified facing | 1 | 41% | Needs review

    Optional: mini charts / alerts cards if dashboard has them — populate with dummy numbers

  Banner at top: "Live demo — sample dashboard with illustrative data"

  CTA below demo: "Start scanning free →" scroll to #lead

DO NOT require login to view this section.

══════════════════════════════════════════════════════════════
SECTION C — HomeLeadCapture (below existing dashboard section)
══════════════════════════════════════════════════════════════

Create or reuse: src/components/home/HomeLeadCapture.tsx
id="lead"

Place IMMEDIATELY AFTER the existing homepage dashboard section.

Match landing lead form design (white card, max-w-5xl centered):

  Title: "Get Your Free Shelf Intelligence Access"
  Sub: "Enter your work email to start scanning. No credit card required."

  Grid 2x2:
    Work email * | Full name
    Company      | Role

  Button (primary navy): "Get more free scans"

  On submit:
    1) POST /landing/lead → save lead
    2) supabase.functions.invoke("send-landing-onboarding", { body: { email, name, signup_url } })
       — use EXISTING RESEND_API_KEY, no new Resend connector
    3) Success:
       - If email sent: "Check your email" + signup link fallback
       - Always show: "Create free account →" button with signup_url

  Footer small text: "We only use your email to set up your Aislix workspace."

══════════════════════════════════════════════════════════════
WIRE INTO src/routes/index.tsx
══════════════════════════════════════════════════════════════

1. Import HomeScanHero, HomeLiveDemoDashboard (or embed in hero), HomeLeadCapture
2. Find existing dashboard/product preview section — do NOT rewrite it
3. Insert <HomeScanHero /> immediately BEFORE dashboard section
4. Insert <HomeLeadCapture /> immediately AFTER dashboard section
5. Live demo button in hero scrolls/expands #live-demo-dashboard

Example structure:

  <SiteHeader />
  … existing top sections unchanged …
  <HomeScanHero onLiveDemo={() => scrollTo('#live-demo-dashboard')} />
  <HomeLiveDemoDashboard />   {/* hidden collapsed until Live demo click, OR always visible below hero */}
  … EXISTING dashboard section — leave code untouched …
  <HomeLeadCapture />
  … existing bottom sections unchanged …

══════════════════════════════════════════════════════════════
QA CHECKLIST
══════════════════════════════════════════════════════════════

✓ Hero matches attached screenshot (copy, layout, shampoo photo, dummy AI analysis card)
✓ Two buttons: "Start scanning free →" and "Live demo"
✓ Live demo shows complete dashboard UI with dummy numbers (no login)
✓ Hero is directly ABOVE existing dashboard section
✓ Lead form is directly BELOW existing dashboard section
✓ All other homepage sections unchanged
✓ Brand colors only — no sky blue
✓ Mobile responsive

Publish when complete.
```
