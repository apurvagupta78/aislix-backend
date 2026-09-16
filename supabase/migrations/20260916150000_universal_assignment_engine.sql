-- Universal Assignment + Scheduling Engine
-- Extends audit_schedules and scan_assignments; adds assignment_campaigns.
--
-- Prerequisites: is_org_member(), is_org_manager() from assigned_scans migration;
-- audit_schedules from audit_waves_2_5; hierarchy_nodes optional (FMCG routing).
-- Apply before 20260916160000_assignment_scheduler_cron.sql.

CREATE TABLE IF NOT EXISTS public.assignment_campaigns (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  operating_model TEXT,
  audit_purpose TEXT,
  template_id UUID REFERENCES public.audit_templates(id) ON DELETE SET NULL,
  template_version INT,
  template_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  assignment_mode TEXT NOT NULL DEFAULT 'assign_now'
    CHECK (assignment_mode IN ('assign_now', 'schedule_once', 'recurring')),
  schedule_config JSONB NOT NULL DEFAULT '{}'::jsonb,
  location_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  team_scope JSONB NOT NULL DEFAULT '{}'::jsonb,
  distribution_strategy TEXT NOT NULL DEFAULT 'equal'
    CHECK (distribution_strategy IN ('manual', 'equal', 'location_based', 'team_based', 'role_based')),
  distribution_plan JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence_policy JSONB,
  require_rca BOOLEAN NOT NULL DEFAULT true,
  reviewer_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  instructions TEXT,
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'scheduled', 'published', 'active', 'paused', 'completed', 'cancelled', 'expired')),
  expected_assignment_count INT NOT NULL DEFAULT 0,
  created_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS assignment_campaigns_org_status_idx
  ON public.assignment_campaigns (org_id, status, created_at DESC);

ALTER TABLE public.assignment_campaigns ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS assignment_campaigns_select ON public.assignment_campaigns;
CREATE POLICY assignment_campaigns_select ON public.assignment_campaigns
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS assignment_campaigns_insert ON public.assignment_campaigns;
CREATE POLICY assignment_campaigns_insert ON public.assignment_campaigns
  FOR INSERT TO authenticated
  WITH CHECK (public.is_org_manager(org_id));

DROP POLICY IF EXISTS assignment_campaigns_update ON public.assignment_campaigns;
CREATE POLICY assignment_campaigns_update ON public.assignment_campaigns
  FOR UPDATE TO authenticated
  USING (public.is_org_manager(org_id))
  WITH CHECK (public.is_org_manager(org_id));

DROP POLICY IF EXISTS assignment_campaigns_delete ON public.assignment_campaigns;
CREATE POLICY assignment_campaigns_delete ON public.assignment_campaigns
  FOR DELETE TO authenticated
  USING (public.is_org_manager(org_id));

DROP POLICY IF EXISTS assignment_campaigns_service ON public.assignment_campaigns;
CREATE POLICY assignment_campaigns_service ON public.assignment_campaigns
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Extend audit_schedules for universal scheduling
ALTER TABLE public.audit_schedules
  ADD COLUMN IF NOT EXISTS assignment_mode TEXT DEFAULT 'recurring',
  ADD COLUMN IF NOT EXISTS timezone TEXT DEFAULT 'Asia/Kolkata',
  ADD COLUMN IF NOT EXISTS recurrence_config JSONB DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS publish_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS due_config JSONB DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS assignee_ids UUID[] DEFAULT '{}'::uuid[],
  ADD COLUMN IF NOT EXISTS hierarchy_node_ids UUID[] DEFAULT '{}'::uuid[],
  ADD COLUMN IF NOT EXISTS distribution_strategy TEXT DEFAULT 'equal',
  ADD COLUMN IF NOT EXISTS distribution_plan JSONB DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS campaign_id UUID REFERENCES public.assignment_campaigns(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS operating_model TEXT,
  ADD COLUMN IF NOT EXISTS template_version INT,
  ADD COLUMN IF NOT EXISTS template_snapshot JSONB,
  ADD COLUMN IF NOT EXISTS evidence_policy JSONB,
  ADD COLUMN IF NOT EXISTS require_rca BOOLEAN DEFAULT true,
  ADD COLUMN IF NOT EXISTS reviewer_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS end_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS max_occurrences INT,
  ADD COLUMN IF NOT EXISTS occurrence_count INT DEFAULT 0;

UPDATE public.audit_schedules SET assignment_mode = 'recurring' WHERE assignment_mode IS NULL;
UPDATE public.audit_schedules SET timezone = 'Asia/Kolkata' WHERE timezone IS NULL;
UPDATE public.audit_schedules SET recurrence_config = '{}'::jsonb WHERE recurrence_config IS NULL;
UPDATE public.audit_schedules SET due_config = '{}'::jsonb WHERE due_config IS NULL;
UPDATE public.audit_schedules SET assignee_ids = '{}'::uuid[] WHERE assignee_ids IS NULL;
UPDATE public.audit_schedules SET hierarchy_node_ids = '{}'::uuid[] WHERE hierarchy_node_ids IS NULL;
UPDATE public.audit_schedules SET distribution_strategy = 'equal' WHERE distribution_strategy IS NULL;
UPDATE public.audit_schedules SET distribution_plan = '[]'::jsonb WHERE distribution_plan IS NULL;
UPDATE public.audit_schedules SET require_rca = true WHERE require_rca IS NULL;
UPDATE public.audit_schedules SET occurrence_count = 0 WHERE occurrence_count IS NULL;

ALTER TABLE public.audit_schedules
  ALTER COLUMN assignment_mode SET DEFAULT 'recurring',
  ALTER COLUMN timezone SET DEFAULT 'Asia/Kolkata',
  ALTER COLUMN recurrence_config SET DEFAULT '{}'::jsonb,
  ALTER COLUMN due_config SET DEFAULT '{}'::jsonb,
  ALTER COLUMN assignee_ids SET DEFAULT '{}'::uuid[],
  ALTER COLUMN hierarchy_node_ids SET DEFAULT '{}'::uuid[],
  ALTER COLUMN distribution_strategy SET DEFAULT 'equal',
  ALTER COLUMN distribution_plan SET DEFAULT '[]'::jsonb,
  ALTER COLUMN require_rca SET DEFAULT true,
  ALTER COLUMN occurrence_count SET DEFAULT 0;

ALTER TABLE public.audit_schedules DROP CONSTRAINT IF EXISTS audit_schedules_assignment_mode_check;
ALTER TABLE public.audit_schedules
  ADD CONSTRAINT audit_schedules_assignment_mode_check
  CHECK (assignment_mode IN ('assign_now', 'schedule_once', 'recurring'));

ALTER TABLE public.audit_schedules DROP CONSTRAINT IF EXISTS audit_schedules_status_check;
ALTER TABLE public.audit_schedules
  ADD CONSTRAINT audit_schedules_status_check
  CHECK (status IN ('draft', 'scheduled', 'active', 'paused', 'completed', 'expired', 'cancelled'));

-- Extend scan_assignments with schedule/campaign linkage
ALTER TABLE public.scan_assignments
  ADD COLUMN IF NOT EXISTS schedule_id UUID REFERENCES public.audit_schedules(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS campaign_id UUID REFERENCES public.assignment_campaigns(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS scheduled_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS hierarchy_node_id UUID,
  ADD COLUMN IF NOT EXISTS assignment_state TEXT DEFAULT 'assigned';

UPDATE public.scan_assignments SET assignment_state = 'assigned' WHERE assignment_state IS NULL;

ALTER TABLE public.scan_assignments DROP CONSTRAINT IF EXISTS scan_assignments_assignment_state_check;
ALTER TABLE public.scan_assignments
  ADD CONSTRAINT scan_assignments_assignment_state_check
  CHECK (assignment_state IN (
    'draft', 'scheduled', 'published', 'assigned', 'accepted', 'in_progress',
    'submitted', 'under_review', 'approved', 'rejected', 'overdue', 'cancelled', 'reaudit_required'
  ));

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'hierarchy_nodes'
  ) AND NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'scan_assignments_hierarchy_node_id_fkey'
  ) THEN
    ALTER TABLE public.scan_assignments
      ADD CONSTRAINT scan_assignments_hierarchy_node_id_fkey
      FOREIGN KEY (hierarchy_node_id) REFERENCES public.hierarchy_nodes(id) ON DELETE SET NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS scan_assignments_schedule_idx
  ON public.scan_assignments (org_id, schedule_id) WHERE schedule_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS scan_assignments_campaign_idx
  ON public.scan_assignments (org_id, campaign_id) WHERE campaign_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS scan_assignments_scheduled_at_idx
  ON public.scan_assignments (org_id, scheduled_at) WHERE scheduled_at IS NOT NULL;

-- Org-level assignment capacity settings (optional)
CREATE TABLE IF NOT EXISTS public.org_assignment_settings (
  org_id UUID PRIMARY KEY REFERENCES public.organizations(id) ON DELETE CASCADE,
  max_daily_assignments_per_employee INT,
  max_concurrent_audits INT,
  estimated_audit_duration_minutes INT,
  reminder_hours INT[] NOT NULL DEFAULT '{24, 12, 4, 1}',
  block_on_conflict BOOLEAN NOT NULL DEFAULT false,
  escalation_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.org_assignment_settings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS org_assignment_settings_select ON public.org_assignment_settings;
CREATE POLICY org_assignment_settings_select ON public.org_assignment_settings
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS org_assignment_settings_manage ON public.org_assignment_settings;
CREATE POLICY org_assignment_settings_manage ON public.org_assignment_settings
  FOR ALL TO authenticated
  USING (public.is_org_manager(org_id))
  WITH CHECK (public.is_org_manager(org_id));

DROP POLICY IF EXISTS org_assignment_settings_service ON public.org_assignment_settings;
CREATE POLICY org_assignment_settings_service ON public.org_assignment_settings
  FOR ALL TO service_role USING (true) WITH CHECK (true);
