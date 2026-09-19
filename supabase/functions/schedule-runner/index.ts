/**
 * Supabase Edge Function — idempotent schedule + reminder processor.
 * Invoke every 5 minutes via Supabase Dashboard → Edge Functions → Schedules
 * when pg_cron is unavailable (e.g. free tier).
 *
 * Requires SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (injected automatically).
 */
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.1";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  const authHeader = req.headers.get("Authorization");
  const cronSecret = Deno.env.get("CRON_SECRET");
  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL") ?? "",
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
  );

  const [schedules, reminders] = await Promise.all([
    supabase.rpc("process_due_audit_schedules", { p_limit: 200 }),
    supabase.rpc("process_assignment_reminders", { p_limit: 500 }),
  ]);

  if (schedules.error) {
    return new Response(JSON.stringify({ error: schedules.error.message }), {
      status: 500,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  if (reminders.error) {
    return new Response(JSON.stringify({ error: reminders.error.message }), {
      status: 500,
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }

  return new Response(
    JSON.stringify({
      ok: true,
      schedules: schedules.data,
      reminders: reminders.data,
      ran_at: new Date().toISOString(),
    }),
    { headers: { ...corsHeaders, "Content-Type": "application/json" } },
  );
});
