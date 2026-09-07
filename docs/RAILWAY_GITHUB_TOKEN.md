# Railway build fix — GITHUB_TOKEN (2 minutes)

The Docker build downloads `models/retailklip_vitb32.pt` (~335 MB). If Supabase fetch fails, it falls back to Git LFS and needs a GitHub token.

**I cannot paste your token into Railway from the codebase** — add it once in the Railway dashboard.

## Steps

1. **Create a GitHub PAT**
   - GitHub → **Settings** → **Developer settings** → **Personal access tokens** → **Tokens (classic)**
   - **Generate new token (classic)**
   - Name: `railway-aislix-lfs`
   - Scope: **`repo`** (read is enough for public repo LFS)
   - Copy the token (`ghp_...`)

2. **Add to Railway**
   - [Railway](https://railway.app) → project **poetic-happiness** → service **aislix-backend**
   - Tab **Variables** → **+ New Variable**
   - Name: `GITHUB_TOKEN`
   - Value: paste `ghp_...`
   - Save (Railway redeploys automatically)

3. **Confirm**
   - Deployments → latest build → **Build Logs**
   - Look for: `Fetching RetailKLIP via Git LFS (authenticated)...` or `RetailKLIP ready (Supabase)`
   - `GET https://aislix-backend-production.up.railway.app/health` → `"retailklip": true`

## Prefer no GitHub token?

If `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are already on Railway **and** the checkpoint is in storage:

```bash
# Run locally once (with Supabase env vars set):
python scripts/upload_retailklip.py
```

Then push the Dockerfile update — build uses Supabase first and skips Git LFS.

## Note

Changing `OPENAI_VISION_REASONING_EFFORT` (or any variable) **redeploys** the service. Build failures on `lfs-fetch` are **not** caused by `low` vs `medium` — they are Git LFS auth / Supabase fetch issues.
