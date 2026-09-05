# Lovable — Homepage demo credibility

Paste entire fenced block into Lovable → Publish.

**API:** `VITE_AISLIX_API_URL=https://aislix-backend-production.up.railway.app`

**Backend note:** `POST /landing/scan` returns `top_brands`, `brand_share`, `brand_share_scope`, `brand_share_denominator`. For the **Top brands by shelf share** chart, bind directly to `top_brands[]` from the API — do **not** recompute client-side from `inventory`. When `brand_share_scope` is `in_audit`, mismatched products (e.g. water on toothpaste shelf) are excluded from the chart denominator.

See chat for full copy-paste prompt block.
