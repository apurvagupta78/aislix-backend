# Lovable Prompt — Team invite emails (make live)

Paste into Lovable chat, then **Publish**.

**Root cause:** `/team` Invite user only upserts `organization_members` with `status: 'invited'`.
No Edge Function sends email — so `hello@aislix.com` shows "Invited" in UI but receives nothing.

---

```
TEAM INVITE EMAILS — wire up sending (P0 for launch)

Current bug: Invite user modal saves organization_members row (status=invited)
but NEVER sends email. User sees "Invited" in team table, inbox is empty.

Implement full flow below.

══════════════════════════════════════════════════════════════
A. SECRETS — Lovable Cloud → Secrets
══════════════════════════════════════════════════════════════

Add secret (get free key at resend.com):

  RESEND_API_KEY = re_xxxxxxxx

Optional (defaults shown):
  INVITE_FROM_EMAIL = onboarding@resend.dev
  INVITE_FROM_NAME = Aislix
  APP_BASE_URL = https://aislix.com

For production deliverability, verify domain app.aislix.com in Resend and set:
  INVITE_FROM_EMAIL = invites@app.aislix.com

Until domain verified, use Resend sandbox from onboarding@resend.dev —
emails only deliver to the Resend account owner's email for testing.

══════════════════════════════════════════════════════════════
B. Edge Function — invite-team-member
══════════════════════════════════════════════════════════════

Create supabase/functions/invite-team-member/index.ts

```typescript
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: corsHeaders });
  }

  try {
    const authHeader = req.headers.get("Authorization");
    if (!authHeader) throw new Error("Missing authorization");

    const supabaseUser = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_ANON_KEY")!,
      { global: { headers: { Authorization: authHeader } } },
    );
    const {
      data: { user },
      error: userError,
    } = await supabaseUser.auth.getUser();
    if (userError || !user) throw new Error("Unauthorized");

    const { orgId, email, role, memberId, resend: isResend } = await req.json();
    const inviteEmail = String(email).trim().toLowerCase();
    if (!orgId || !inviteEmail) throw new Error("orgId and email required");

    const admin = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
    );

    // Caller must be manager+ in org
    const { data: callerMember } = await admin
      .from("organization_members")
      .select("role")
      .eq("org_id", orgId)
      .eq("user_id", user.id)
      .eq("status", "active")
      .maybeSingle();

    if (!callerMember || !["owner", "admin", "manager"].includes(callerMember.role)) {
      throw new Error("Forbidden");
    }

    const { data: org } = await admin
      .from("organizations")
      .select("name")
      .eq("id", orgId)
      .single();

    const { data: inviterProfile } = await admin
      .from("profiles")
      .select("full_name")
      .eq("id", user.id)
      .maybeSingle();

    const orgName = org?.name ?? "your organization";
    const inviterName = inviterProfile?.full_name ?? user.email ?? "A team admin";
    const baseUrl = Deno.env.get("APP_BASE_URL") ?? "https://aislix.com";
    const acceptUrl =
      `${baseUrl}/accept-invite?org=${encodeURIComponent(orgId)}` +
      `&email=${encodeURIComponent(inviteEmail)}`;

    const resendKey = Deno.env.get("RESEND_API_KEY");
    if (!resendKey) throw new Error("RESEND_API_KEY not configured");

    const fromEmail = Deno.env.get("INVITE_FROM_EMAIL") ?? "onboarding@resend.dev";
    const fromName = Deno.env.get("INVITE_FROM_NAME") ?? "Aislix";

    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${resendKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: `${fromName} <${fromEmail}>`,
        to: [inviteEmail],
        subject: `You're invited to ${orgName} on Aislix`,
        html: `
          <p>Hi,</p>
          <p><strong>${inviterName}</strong> invited you to join
          <strong>${orgName}</strong> on Aislix as <strong>${role ?? "member"}</strong>.</p>
          <p><a href="${acceptUrl}">Accept invitation</a></p>
          <p>Or copy this link: ${acceptUrl}</p>
          <p>If you don't have an account yet, you'll be able to sign up after clicking the link.</p>
          <p>— Aislix</p>
        `,
      }),
    });

    const resendBody = await res.json();
    if (!res.ok) {
      console.error("Resend error", resendBody);
      throw new Error(resendBody?.message ?? "Failed to send invite email");
    }

    // Mark invite timestamp (optional column — skip if missing)
    if (memberId) {
      await admin
        .from("organization_members")
        .update({ invited_at: new Date().toISOString() })
        .eq("id", memberId);
    }

    return new Response(
      JSON.stringify({ ok: true, resendId: resendBody.id }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (e) {
    const message = e instanceof Error ? e.message : "Invite email failed";
    return new Response(JSON.stringify({ error: message }), {
      status: 400,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
});
```

Deploy edge function. Grant invoke to authenticated users.

══════════════════════════════════════════════════════════════
C. Team page — CALL edge function after upsert
══════════════════════════════════════════════════════════════

In /team Invite user modal, AFTER successful organization_members upsert:

```typescript
// 1. Upsert member row (existing code)
const { data: member, error: upsertError } = await supabase
  .from("organization_members")
  .upsert(
    {
      org_id: currentOrgId,
      invited_email: email.toLowerCase(),
      role,
      status: "invited",
      invited_by: user.id,
      store_ids: selectedStoreIds.length ? selectedStoreIds : null,
    },
    { onConflict: "org_id,invited_email" },
  )
  .select("id")
  .single();

if (upsertError) throw upsertError;

// 2. SEND EMAIL — this is the missing step
const { data: sendResult, error: sendError } = await supabase.functions.invoke(
  "invite-team-member",
  {
    body: {
      orgId: currentOrgId,
      email: email.toLowerCase(),
      role,
      memberId: member?.id,
    },
  },
);

if (sendError) {
  console.error(sendError);
  toast.error(
    "Invite saved but email could not be sent. Use Resend on pending invite.",
  );
} else {
  toast.success(`Invitation sent to ${email}`);
}
```

Pending invites row: add **Resend** button calling same edge function with resend: true.

If upsert succeeds but email fails, show error toast — do NOT silently succeed.

══════════════════════════════════════════════════════════════
D. Accept invite page — /accept-invite
══════════════════════════════════════════════════════════════

Create route /accept-invite

Query params: org, email

Flow:
1. Read org + email from URL
2. If not logged in → redirect /signup?email={email}&redirect=/accept-invite?org=...&email=...
   OR /login with same redirect
3. If logged in (or after signup):
   ```typescript
   const { data: { user } } = await supabase.auth.getUser();
   await supabase
     .from("organization_members")
     .update({
       user_id: user.id,
       status: "active",
       invited_email: null,
     })
     .eq("org_id", orgId)
     .eq("invited_email", email.toLowerCase())
     .eq("status", "invited");

   // Skip onboarding for invited members
   await supabase.rpc("complete_onboarding"); // or set onboarding_completed_at

   navigate("/my-scans", { replace: true });
   toast.success("Welcome to the team!");
   ```

Register /accept-invite in router and Supabase redirect URLs.

══════════════════════════════════════════════════════════════
E. Optional SQL — invited_at column
══════════════════════════════════════════════════════════════

```sql
ALTER TABLE public.organization_members
  ADD COLUMN IF NOT EXISTS invited_at TIMESTAMPTZ;
```

══════════════════════════════════════════════════════════════
F. Lovable Cloud → Emails tab
══════════════════════════════════════════════════════════════

After deploy, send test invite and check Cloud → Emails for delivery logs.
If Resend returns 403, domain not verified — use sandbox or verify app.aislix.com.

══════════════════════════════════════════════════════════════
TEST
══════════════════════════════════════════════════════════════

1. Add RESEND_API_KEY to Secrets
2. Deploy invite-team-member function
3. /team → Invite hello@aislix.com (or your personal email)
4. Toast: "Invitation sent to …"
5. Email arrives within 1 min (check spam)
6. Click Accept → signup/login → lands on /my-scans as member
7. Team table: status Active

Publish when done.
```

---

## Quick diagnostic (SQL)

Check pending invite exists but no email was sent (expected until fix):

```sql
SELECT om.invited_email, om.role, om.status, om.invited_at, o.name AS org_name
FROM public.organization_members om
JOIN public.organizations o ON o.id = om.org_id
WHERE om.status = 'invited'
ORDER BY om.created_at DESC;
```

## Resend sandbox note

Until `app.aislix.com` is verified in Resend, emails from `onboarding@resend.dev` **only deliver to the email address on your Resend account**. For real recipients like `hello@aislix.com`, verify the domain first.
