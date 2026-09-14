-- Digital Audit Waves 2–5: schedules, AI-assisted flags, intelligence indexes

-- ============ Recurring audit schedules ============

CREATE TABLE IF NOT EXISTS public.audit_schedules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  store_id UUID NOT NULL REFERENCES public.stores(id) ON DELETE CASCADE,
  assignee_id UUID NOT NULL REFERENCES auth.users(id),
  scope_type TEXT NOT NULL DEFAULT 'planogram'
    CHECK (scope_type IN ('category', 'sub_category', 'location', 'planogram')),
  scope_values JSONB NOT NULL DEFAULT '{}'::jsonb,
  audit_mode TEXT NOT NULL DEFAULT 'digital'
    CHECK (audit_mode IN ('ai', 'digital')),
  cadence TEXT NOT NULL DEFAULT 'weekly'
    CHECK (cadence IN ('daily', 'weekly', 'monthly', 'special')),
  day_of_week INT CHECK (day_of_week IS NULL OR (day_of_week >= 0 AND day_of_week <= 6)),
  day_of_month INT CHECK (day_of_month IS NULL OR (day_of_month >= 1 AND day_of_month <= 28)),
  next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_run_at TIMESTAMPTZ,
  active BOOLEAN NOT NULL DEFAULT true,
  instructions TEXT,
  created_by UUID NOT NULL REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_schedules_due_idx
  ON public.audit_schedules (org_id, active, next_run_at);

ALTER TABLE public.audit_schedules ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS audit_schedules_select ON public.audit_schedules;
CREATE POLICY audit_schedules_select ON public.audit_schedules
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS audit_schedules_insert ON public.audit_schedules;
CREATE POLICY audit_schedules_insert ON public.audit_schedules
  FOR INSERT TO authenticated
  WITH CHECK (public.is_org_manager(org_id));

DROP POLICY IF EXISTS audit_schedules_update ON public.audit_schedules;
CREATE POLICY audit_schedules_update ON public.audit_schedules
  FOR UPDATE TO authenticated
  USING (public.is_org_manager(org_id));

DROP POLICY IF EXISTS audit_schedules_delete ON public.audit_schedules;
CREATE POLICY audit_schedules_delete ON public.audit_schedules
  FOR DELETE TO authenticated
  USING (public.is_org_manager(org_id));

-- ============ AI-assisted verification (digital vs AI qty) ============

ALTER TABLE public.digital_audit_lines
  ADD COLUMN IF NOT EXISTS ai_suggested_qty INT,
  ADD COLUMN IF NOT EXISTS ai_assisted_flag BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.digital_audit_lines.ai_suggested_qty IS
  'Latest AI audit qty for same store+SKU — used for AI-Assisted verification.';
COMMENT ON COLUMN public.digital_audit_lines.ai_assisted_flag IS
  'True when |actual_qty - ai_suggested_qty| exceeds threshold (default 2).';

-- Intelligence query indexes
CREATE INDEX IF NOT EXISTS digital_audit_lines_org_store_idx
  ON public.digital_audit_lines (org_id, store_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS shelf_scans_audit_mode_status_idx
  ON public.shelf_scans (org_id, audit_mode, submission_status, submitted_at DESC);
