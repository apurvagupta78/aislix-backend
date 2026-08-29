-- Landing-page anonymous shelf scans + lead capture (LinkedIn ads funnel).
-- Run in Lovable Cloud SQL editor before enabling /landing/* API in production.

CREATE TABLE IF NOT EXISTS public.landing_demo_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_token TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- attribution
  utm_source TEXT,
  utm_medium TEXT,
  utm_campaign TEXT,
  utm_content TEXT,
  utm_term TEXT,
  referrer TEXT,
  user_agent TEXT,
  ip_hash TEXT,

  -- scan
  scan_id TEXT,
  sample_id TEXT,
  image_storage_path TEXT,
  category TEXT,
  scan_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (scan_status IN ('pending', 'processing', 'completed', 'failed')),
  scan_error TEXT,
  scan_result JSONB,

  -- optional lead form (before signup)
  lead_email TEXT,
  lead_name TEXT,
  lead_company TEXT,
  lead_phone TEXT,
  lead_captured_at TIMESTAMPTZ,

  -- signup conversion
  converted_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  signed_up_at TIMESTAMPTZ,
  signup_completed BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_landing_demo_sessions_ip_created
  ON public.landing_demo_sessions (ip_hash, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_landing_demo_sessions_lead_email
  ON public.landing_demo_sessions (lead_email)
  WHERE lead_email IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_landing_demo_sessions_converted
  ON public.landing_demo_sessions (converted_user_id)
  WHERE converted_user_id IS NOT NULL;

COMMENT ON TABLE public.landing_demo_sessions IS
  'Anonymous /retail-intelligence demo scans from LinkedIn ads. Written by Railway backend (service_role).';

-- Storage bucket for uploaded shelf photos (create in Supabase Storage if missing):
--   bucket id: landing-scans (private)
-- Backend uploads via service_role; no public anon read required.

ALTER TABLE public.landing_demo_sessions ENABLE ROW LEVEL SECURITY;

-- No anon/authenticated policies — backend uses service_role only.
REVOKE ALL ON public.landing_demo_sessions FROM anon, authenticated;
GRANT ALL ON public.landing_demo_sessions TO service_role;
