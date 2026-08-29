# Lovable Prompt — Landing onboarding email edge function

Paste into Lovable **before** testing lead form email delivery.

**Why:** `RESEND_API_KEY` lives in Lovable Cloud secrets (team invites), not Railway. The backend calls this edge function to send onboarding emails.

---

```
DEPLOY EDGE FUNCTION — send-landing-onboarding

1. Create supabase/functions/send-landing-onboarding/index.ts

import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }
  try {
    const { email, name, signup_url } = await req.json();
    if (!email || !signup_url) {
      throw new Error("email and signup_url are required");
    }

    const resendKey = Deno.env.get("RESEND_API_KEY");
    if (!resendKey) throw new Error("RESEND_API_KEY not configured");

    const fromEmail = Deno.env.get("INVITE_FROM_EMAIL") ?? "onboarding@resend.dev";
    const fromName = Deno.env.get("INVITE_FROM_NAME") ?? "Aislix";
    const greeting = name ? `Hi ${name},` : "Hi,";

    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${resendKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: `${fromName} <${fromEmail}>`,
        to: [email],
        subject: "Your Aislix free workspace — complete signup",
        html: `
          <p>${greeting}</p>
          <p>Thanks for trying Aislix shelf intelligence. You're one step away from your free workspace with <strong>3 shelf scans</strong>.</p>
          <p><a href="${signup_url}">Create your free Aislix account →</a></p>
          <p>Or copy this link: ${signup_url}</p>
          <p>— Aislix</p>
        `,
      }),
    });

    const body = await res.json();
    if (!res.ok) {
      console.error("Resend error", body);
      throw new Error(body?.message ?? "Failed to send onboarding email");
    }

    return new Response(JSON.stringify({ ok: true, resendId: body.id }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : "Onboarding email failed";
    return new Response(JSON.stringify({ ok: false, error: message }), {
      status: 400,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
});

2. Deploy function (Lovable Cloud → Edge Functions)

3. Secrets must already exist:
   RESEND_API_KEY
   INVITE_FROM_EMAIL = onboarding@resend.dev   (until aislix.com domain verified in Resend)
   INVITE_FROM_NAME = Aislix

4. IMPORTANT — Resend sandbox:
   Until aislix.com is verified, onboarding@resend.dev ONLY delivers to the email on your Resend account.
   For testing with apurvagupta78@gmail.com you MUST verify aislix.com domain in Resend OR add that Gmail to Resend test recipients.

══════════════════════════════════════════════════════════════
FRONTEND — lead form success UI fix
══════════════════════════════════════════════════════════════

After POST /landing/lead, read response:

const data = await res.json();

if (data.email_sent) {
  // Show "Check your email" state
} else {
  // Show: "Create your account now" with primary button → data.signup_url
  // Do NOT say "check your email" when email_sent === false
}

Always show prominent button:
  "Create free account →" href={data.signup_url || signupUrl()}

Optional fallback — also invoke from frontend (belt and suspenders):
await supabase.functions.invoke("send-landing-onboarding", {
  body: { email, name, signup_url: data.signup_url },
});
```
