-- Landing lead role + onboarding email tracking.
-- Run in Lovable Cloud SQL editor.

ALTER TABLE public.landing_demo_sessions
  ADD COLUMN IF NOT EXISTS lead_role TEXT,
  ADD COLUMN IF NOT EXISTS onboarding_email_sent_at TIMESTAMPTZ;
