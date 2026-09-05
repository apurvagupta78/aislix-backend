# Lovable — Final prompt: B2B credibility fixes (homepage + dashboard demo)

Paste the block below into Lovable chat, then **Publish**.

Priority order: epoch dates → meta tags → plan/scan mismatch → footer links.

---

```
B2B CREDIBILITY FIXES — aislix.com homepage + demo dashboard

Claude audit found live bugs that hurt enterprise credibility. Fix ALL below in one pass.

══════════════════════════════════════════════════════════════
P0 — EPOCH DATE BUG (Dec 31 1969 / Jan 31 1970 everywhere)
══════════════════════════════════════════════════════════════

Problem:
- Homepage demo dashboard scan timestamps show "Dec 31, 1969" or "Dec 29, 1969"
- Account summary renewal date shows "Jan 31, 1970"
- Classic Unix epoch-zero bug: new Date(0), new Date(null), or missing created_at/scanned_at/period_end

Root cause:
- HomeLiveDemoDashboard / homepage dashboard preview reuses real ScanHistory or dashboard components
- Dummy rows have NO valid date fields → formatters render epoch zero

Fix — create src/lib/format-date.ts:

export function formatDisplayDate(
  value: string | number | null | undefined,
  fallback = "—"
): string {
  if (value === null || value === undefined || value === "" || value === 0) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime()) || date.getTime() < 86400000) return fallback;
  return date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

Apply formatDisplayDate EVERYWHERE dates render:
- Homepage demo dashboard (recent scans table)
- Scan history rows on marketing pages
- Dashboard account summary "Renews on …"
- Any demo/mock data arrays

Demo data — use realistic ISO strings (NOT 0 or null):

const DEMO_SCAN_HISTORY = [
  { id: "demo-1", location: "A-1-L", products: 31, scanned_at: new Date(Date.now() - 2 * 3600000).toISOString() },
  { id: "demo-2", location: "A-1-Z", products: 28, scanned_at: new Date(Date.now() - 26 * 3600000).toISOString() },
  { id: "demo-3", location: "B-2-S", products: 45, scanned_at: new Date(Date.now() - 3 * 86400000).toISOString() },
];

Demo account summary:
  period_end: new Date(Date.now() + 18 * 86400000).toISOString()  // ~18 days from now
  // NEVER use 0, null, or omit period_end on demo billing card

Live landing scans: POST /landing/scan now returns scanned_at (ISO). Use that for live demo results.

Rule: NEVER call toLocaleDateString on raw DB fields without formatDisplayDate guard.

══════════════════════════════════════════════════════════════
P0 — LOVABLE METADATA LEAK (OG / Twitter / social share)
══════════════════════════════════════════════════════════════

Problem:
- og:image URL contains "...lovable.app-..." in the path
- twitter:site is @Lovable instead of Aislix
- Sharing aislix.com on LinkedIn/X exposes the no-code builder

Fix in index.html AND react-helmet / meta component for ALL public routes:

<meta property="og:title" content="Aislix — AI-Powered Retail Shelf Auditing" />
<meta property="og:description" content="Turn a shelf photo into a complete retail audit in ~60 seconds. Product detection, planogram compliance, and actionable insights." />
<meta property="og:url" content="https://aislix.com/" />
<meta property="og:type" content="website" />
<meta property="og:site_name" content="Aislix" />
<meta property="og:image" content="https://aislix.com/og-image.png" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />

<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:site" content="@aislix" />
<meta name="twitter:title" content="Aislix — AI-Powered Retail Shelf Auditing" />
<meta name="twitter:description" content="Turn a shelf photo into a complete retail audit in ~60 seconds." />
<meta name="twitter:image" content="https://aislix.com/og-image.png" />

Actions:
1. REMOVE all Lovable default meta tags (lovable.app URLs, @Lovable)
2. Upload branded og-image.png to public/ (1200×630, Aislix logo + shelf photo + tagline)
3. Search codebase for "lovable" in meta/og/twitter — delete or replace every hit
4. Verify with https://www.opengraph.xyz/?url=https://aislix.com after publish

══════════════════════════════════════════════════════════════
P1 — PROFESSIONAL PLAN SCAN COUNT MISMATCH
══════════════════════════════════════════════════════════════

Problem:
- Demo dashboard shows "Professional plan, 128/Unlimited scans, 372 scans remaining"
- Pricing table correctly says Professional = 5,000 scans/month (NOT unlimited)
- "Unlimited" on Professional refers to SCAN HISTORY only — not monthly scan quota

Fix — replace src/lib/subscription-limits.ts with backend copy from docs/subscription-limits.ts:

Key changes in normalizeUsageSummary():
- When RPC fields missing, fall back to src/lib/pricing.ts plan catalogue
- Professional: scans_included = 5000, scan_limit_label = "5,000 scans / month"
- ONLY Enterprise gets scans_included = null (unlimited monthly scans)

Use formatUsageLabel() everywhere — never hand-roll "Unlimited scans" for paid tiers:

  Professional with 128 used → "128 / 5,000 scans used this month"
  Enterprise → "128 scans · unlimited plan"

Demo dashboard account card (if static):
  plan: "Professional"
  scans_used: 128
  scans_included: 5000
  scans_remaining: 4872
  scan_limit_label: "5,000 scans / month"
  // NOT "Unlimited scans"

Pricing page + dashboard usage widget must match docs/pricing.ts:
  Free: 3 / 24h | Starter: 300 | Growth: 3,000 | Professional: 5,000 | Enterprise: Unlimited

══════════════════════════════════════════════════════════════
P2 — FOOTER LINKS (enterprise positioning)
══════════════════════════════════════════════════════════════

Problem:
- Documentation, Help Center, Security, API all route to contact form with pre-filled subject
- Fine as stopgap but undercuts enterprise positioning

Fix (pick one per link — do NOT leave misleading labels):

| Link | Fix |
|------|-----|
| Documentation | Rename to "Contact us" OR add /docs stub with Getting Started + API overview |
| Help Center | Rename to "Support" → mailto:support@aislix.com or /contact?topic=support |
| Security | Add /security page: data handling, Supabase/Railway, encryption at rest, contact for SOC2 |
| API | Rename to "API access" → /contact?topic=api OR brief /developers page with POST /scan docs link |

Keep Careers / Blog / Status as "Soon" but style as disabled text — not broken links.

══════════════════════════════════════════════════════════════
FILES TO TOUCH
══════════════════════════════════════════════════════════════

- src/lib/format-date.ts (NEW)
- src/lib/subscription-limits.ts (REPLACE from backend docs)
- src/components/home/HomeLiveDemoDashboard.tsx — valid demo dates + correct plan stats
- Homepage dashboard preview section (if separate from HomeLiveDemoDashboard)
- src/components/layout/SiteFooter.tsx — link labels/pages
- index.html + src/components/seo/MetaTags.tsx (or equivalent)
- public/og-image.png (NEW branded asset)

Do NOT change: auth, scan pipeline, Supabase schema, API URLs.

══════════════════════════════════════════════════════════════
QA CHECKLIST (verify before publish)
══════════════════════════════════════════════════════════════

□ Homepage demo scans show "Today" / "Yesterday" / real dates — NEVER 1969/1970
□ Account renewal shows a future date or "—" — NEVER Jan 1970
□ Professional demo shows "128 / 5,000 scans used" — NOT "Unlimited"
□ View page source — no lovable.app in og:image; twitter:site is @aislix (or removed if no handle yet)
□ opengraph.xyz preview shows Aislix branding
□ Footer links are honest (real page or renamed — not "Documentation" → contact form)
□ Mobile layout unchanged

Ship all P0 fixes first — these are what B2B buyers spot in 10 seconds.
```

---

**Backend (already done / no Lovable action):**
- `POST /landing/scan` now returns `scanned_at` (ISO timestamp)
- `docs/subscription-limits.ts` fixed — Professional defaults to 5,000 not unlimited

Copy `docs/subscription-limits.ts` → Lovable `src/lib/subscription-limits.ts` when applying P1.
