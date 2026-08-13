# Lovable Prompt — Planogram CSV upload error + persistent error UI

Paste into Lovable chat, then **Publish**.

Backend fix (CORS for aislix.com) is in Railway `main.py` — redeploy after merge.

---

```
PLANOGRAM CSV UPLOAD — fix "Network error" + keep errors visible

Symptom on /store-master (Planogram page):
- User selects CSV file → toast: "Network error. Check your connection and try again."
- Error disappears after a few seconds — user may miss it

══════════════════════════════════════════════════════════════
1. DIAGNOSE — why "Network error"?
══════════════════════════════════════════════════════════════

Trace the CSV upload handler (Planogram / Store Master page):

- What URL does it POST to? (should be Railway backend)
  POST {VITE_AISLIX_API_URL}/planogram/parse-csv
  Example: https://aislix-backend-production.up.railway.app/planogram/parse-csv

Common causes of generic "Network error":
a) Wrong or missing VITE_AISLIX_API_URL env var
b) CORS blocked (frontend on aislix.com / app.aislix.com, backend not allowing origin)
   → Backend adds app.aislix.com + aislix.com to CORS — redeploy Railway
c) fetch() throws before response (no internet, SSL, blocked mixed content)
d) Catch block maps ALL errors to "Network error" hiding real message

Fix the catch block — show the REAL error:

```typescript
async function parsePlanogramCsv(file: File) {
  setCsvError(null);
  setCsvLoading(true);
  try {
    const apiUrl = import.meta.env.VITE_AISLIX_API_URL;
    if (!apiUrl) throw new Error("Scan API URL is not configured. Contact support.");

    const form = new FormData();
    form.append("file", file);

    const res = await fetch(`${apiUrl.replace(/\/$/, "")}/planogram/parse-csv`, {
      method: "POST",
      body: form,
    });

    const body = await res.json().catch(() => ({}));

    if (!res.ok) {
      const detail = body?.detail ?? body?.message ?? res.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }

    if (body.error_count > 0 && body.valid_count === 0) {
      setCsvError(
        `CSV has ${body.error_count} error(s): ${(body.errors ?? []).slice(0, 5).join("; ")}`,
      );
    }

    setPreviewRows(body.rows ?? []);
    setCsvPreview(body);
  } catch (e) {
    const message =
      e instanceof TypeError && e.message === "Failed to fetch"
        ? "Could not reach the Aislix server. Check your connection, or try again in a moment. If this persists, the API may be blocked (CORS) — contact support."
        : e instanceof Error
          ? e.message
          : "Upload failed";
    setCsvError(message);
  } finally {
    setCsvLoading(false);
  }
}
```

Verify Lovable env:
  VITE_AISLIX_API_URL = your Railway backend URL (no trailing slash)

══════════════════════════════════════════════════════════════
2. PERSISTENT ERROR UI — do NOT auto-dismiss errors
══════════════════════════════════════════════════════════════

Replace auto-dismiss toast for planogram CSV errors with a STICKY inline alert
that stays until the user dismisses it or uploads again successfully.

Rules:
- SUCCESS toasts: may auto-dismiss (3–5 sec) — OK
- ERROR toasts on planogram upload: NEVER auto-dismiss OR use inline Alert instead

Implement on Planogram / store-master CSV section:

```tsx
{csvError && (
  <Alert variant="destructive" className="relative pr-10">
    <AlertCircle className="h-4 w-4" />
    <AlertTitle>Planogram upload failed</AlertTitle>
    <AlertDescription className="whitespace-pre-wrap">{csvError}</AlertDescription>
    <button
      type="button"
      className="absolute right-3 top-3 text-muted-foreground hover:text-foreground"
      aria-label="Dismiss error"
      onClick={() => setCsvError(null)}
    >
      <X className="h-4 w-4" />
    </button>
  </Alert>
)}
```

If using toast for errors anywhere on this page:
```typescript
toast.error(message, { duration: Infinity }); // or 60000 — NOT 3000
```

Apply same pattern to:
- Save draft failures
- Activate planogram failures
- Manual row validation errors (inline under form, not fleeting toast)

══════════════════════════════════════════════════════════════
3. CSV validation errors — show in UI, not only toast
══════════════════════════════════════════════════════════════

When /planogram/parse-csv returns row errors, show:
- Red inline alert summarizing error_count
- Preview table with invalid rows highlighted + per-row error text
- Do NOT say "Network error" for validation failures (those are 200 OK with errors array)

Required CSV columns:
  location, category, sub_category, brand, product_name, expected_qty

Optional CSV columns:
  variant, sku, shelf_position

Full header (template download via GET /planogram/csv-template):
  location,category,sub_category,brand,product_name,variant,expected_qty,sku,shelf_position

══════════════════════════════════════════════════════════════
4. TEST
══════════════════════════════════════════════════════════════

1. Upload valid CSV → preview table, no error alert
2. Upload invalid CSV (missing brand column) → persistent red alert with column message
3. Disconnect wifi / wrong API URL → persistent alert with clear message (not generic only)
4. Error stays on screen 30+ seconds until user clicks X
5. Works on aislix.com AND aislix.lovable.app after Railway CORS redeploy

Publish when done.
```
