# Lovable — Full website audit fixes (aislix.com)

Paste into Lovable chat, then **Publish**.

Also run SQL: `supabase/migrations/20260905120000_free_plan_5_scans.sql` in Cloud SQL.

---

```
FULL WEBSITE AUDIT FIXES — aislix.com (March 2026 audit)

Already fixed on production (do NOT regress):
✓ Demo dashboard dates (no more Dec 1969)
✓ Professional plan shows 128 / 5,000 scans (not Unlimited)
✓ OG meta tags text (@aislix, og:image URL in HTML)
✓ /security page exists
✓ Live demo scan works (POST /landing/scan → 116 products, 17 SKUs)

══════════════════════════════════════════════════════════════
P0 — BROKEN og-image.png (HTTP 500)
══════════════════════════════════════════════════════════════

Problem:
- Meta tags point to https://aislix.com/og-image.png
- URL returns 500 — LinkedIn/X previews show broken image

Fix:
1. Add public/og-image.png (1200×630 PNG, <300KB)
   Content: Aislix logo + shelf photo + "Audit every aisle from a single photo"
2. Verify after publish: curl -I https://aislix.com/og-image.png → 200
3. Test: https://www.opengraph.xyz/?url=https://aislix.com

Do NOT reference lovable.app in og:image.

══════════════════════════════════════════════════════════════
P0 — Free plan copy mismatch (3 vs 5 scans)
══════════════════════════════════════════════════════════════

Problem:
- Homepage + pricing say "5 scans / 24 hours"
- /signup still says "3 free shelf scans every day"
- Backend migration sets free plan to 5 (run SQL migration)

Fix ALL copy to "5 scans every 24 hours":
- /signup subtitle
- Onboarding emails (edge function send-landing-onboarding if hardcoded)
- Dashboard limit toasts / blocked messages
- src/lib/pricing.ts — copy from backend docs/pricing.ts (free = 5)
- src/lib/subscription-limits.ts — copy from backend docs/subscription-limits.ts

Blocked message: "You've used your 5 free scans. You can scan again after …"

══════════════════════════════════════════════════════════════
P1 — Demo dashboard "View" links redirect to /login
══════════════════════════════════════════════════════════════

Problem:
- Homepage demo "Recent scans" table has View / View results links
- Clicking sends user to /login — confusing on marketing page

Fix (pick one):
A) Remove href from demo View links; show toast "Sign up to view full scan history"
B) Replace with button "Create free account →" linking to /signup
C) Open inline modal with static demo result snippet (no auth)

Add aria-disabled or cursor-not-allowed styling so links don't look clickable if removed.

Files: src/components/home/*DashboardDemo*, dashboard-demo-*.ts

══════════════════════════════════════════════════════════════
P1 — Live demo empty state on first load
══════════════════════════════════════════════════════════════

Problem:
- "See What AI Sees" section shows "—" and "No scan results yet" until user clicks
- First impression looks broken

Fix:
- On mount, show PREVIEW metrics from last successful demo OR static preview:
    Products: 116 | SKUs: 17 | Shelf health: 74%
- Show toothpaste sample image by default (already preloaded)
- Optional: auto-run sample scan once per session on scroll-into-view
- Keep "Try Sample Shelf Below" as explicit CTA

══════════════════════════════════════════════════════════════
P2 — Executive summary truncated in live demo
══════════════════════════════════════════════════════════════

Problem:
- Summary text cuts off mid-sentence ("Mouthwash and Fr…")

Fix:
- Allow 3–4 lines with line-clamp-4 OR expandable "Read more"
- Full text visible on mobile

══════════════════════════════════════════════════════════════
P2 — Pricing compare table empty cells
══════════════════════════════════════════════════════════════

On /pricing compare table, ensure checkmarks for:
- Professional: Faster AI processing ✓
- Growth+: Historical trends ✓
- Enterprise: Custom AI models ✓

Empty cells look like missing features.

══════════════════════════════════════════════════════════════
P2 — Pricing FAQ accordion content
══════════════════════════════════════════════════════════════

Ensure each FAQ has visible answer text when expanded:
- How is a scan counted?
- What happens when I hit my monthly limit?
- Do you issue GST invoices?
- Can I change or cancel my plan later?

If using Radix Accordion, verify Content is not empty.

══════════════════════════════════════════════════════════════
P3 — Minor polish
══════════════════════════════════════════════════════════════

- Demo notifications: already have dates ✓
- Footer "Careers Soon" / "Blog Soon" — keep as disabled, not links
- /signup Google/Apple buttons — verify OAuth redirect URLs in Supabase
- Nav "Demo" link → scroll to #live-demo or live demo section

══════════════════════════════════════════════════════════════
QA CHECKLIST
══════════════════════════════════════════════════════════════

□ og-image.png returns 200
□ /signup says 5 scans (not 3)
□ Demo View links don't surprise-redirect to login
□ Live demo shows preview metrics before first click
□ Try Sample Shelf → 116 products / 17 SKUs / 74% health
□ Free user blocked message mentions 5 scans
□ opengraph.xyz preview looks correct

Publish when all P0 + P1 pass.
```

---

**Backend (Railway):** landing onboarding email text updated to 5 scans — redeploy after commit.

**SQL:** Run `20260905120000_free_plan_5_scans.sql` in Supabase.
