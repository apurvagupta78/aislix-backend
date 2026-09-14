-- Expiry Control module: inspections, packet observations, evidence, quarantine, disposition.
-- Additive only. Reuses stores, organization_members, notifications, findings.

-- ============ Role grants (supervisor / reviewer beyond org role) ============

CREATE TABLE IF NOT EXISTS public.expiry_role_grants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  grant_role TEXT NOT NULL CHECK (grant_role IN ('supervisor', 'reviewer', 'admin')),
  store_id UUID REFERENCES public.stores(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, user_id, grant_role, store_id)
);

ALTER TABLE public.expiry_role_grants ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_role_grants_select ON public.expiry_role_grants
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
CREATE POLICY expiry_role_grants_manage ON public.expiry_role_grants
  FOR ALL TO authenticated
  USING (public.is_org_manager(org_id))
  WITH CHECK (public.is_org_manager(org_id));

-- ============ Policy versions ============

CREATE TABLE IF NOT EXISTS public.expiry_policy_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  name TEXT NOT NULL,
  version INT NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'archived')),
  rules JSONB NOT NULL DEFAULT '{}'::jsonb,
  near_expiry_days INT NOT NULL DEFAULT 7,
  required_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  date_types TEXT[] NOT NULL DEFAULT ARRAY['expiry', 'use_by', 'best_before'],
  assurance_levels TEXT[] NOT NULL DEFAULT ARRAY['standard', 'high'],
  quarantine_sla_hours INT NOT NULL DEFAULT 24,
  retention_days INT NOT NULL DEFAULT 365,
  published_at TIMESTAMPTZ,
  created_by UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, name, version)
);

ALTER TABLE public.expiry_policy_versions ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_policy_versions_select ON public.expiry_policy_versions
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
CREATE POLICY expiry_policy_versions_manage ON public.expiry_policy_versions
  FOR ALL TO authenticated
  USING (public.is_org_manager(org_id))
  WITH CHECK (public.is_org_manager(org_id));

-- ============ Location catalog ============

CREATE TABLE IF NOT EXISTS public.expiry_locations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  store_id UUID REFERENCES public.stores(id) ON DELETE CASCADE,
  location_type TEXT NOT NULL CHECK (location_type IN (
    'main_shelf', 'promo_display', 'checkout_display', 'backroom', 'returns_holding', 'custom'
  )),
  label TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, store_id, label)
);

ALTER TABLE public.expiry_locations ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_locations_select ON public.expiry_locations
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
CREATE POLICY expiry_locations_manage ON public.expiry_locations
  FOR ALL TO authenticated
  USING (public.is_org_manager(org_id))
  WITH CHECK (public.is_org_manager(org_id));

-- ============ Inspection assignments (planner) ============

CREATE TABLE IF NOT EXISTS public.expiry_inspection_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  store_id UUID NOT NULL REFERENCES public.stores(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN (
    'draft', 'assigned', 'in_progress', 'completed', 'cancelled'
  )),
  location_ids UUID[] NOT NULL DEFAULT '{}',
  required_location_ids UUID[] NOT NULL DEFAULT '{}',
  sku_filters JSONB NOT NULL DEFAULT '{}'::jsonb,
  category_filters JSONB NOT NULL DEFAULT '{}'::jsonb,
  auditor_id UUID NOT NULL REFERENCES auth.users(id),
  reviewer_id UUID REFERENCES auth.users(id),
  due_at TIMESTAMPTZ,
  schedule_type TEXT NOT NULL DEFAULT 'one_off' CHECK (schedule_type IN ('one_off', 'recurring')),
  schedule_cron TEXT,
  expected_stock_source TEXT NOT NULL DEFAULT 'manual',
  expected_stock_snapshot_at TIMESTAMPTZ,
  assurance_level TEXT NOT NULL DEFAULT 'standard' CHECK (assurance_level IN ('standard', 'high')),
  policy_version_id UUID REFERENCES public.expiry_policy_versions(id) ON DELETE SET NULL,
  policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  instructions TEXT,
  created_by UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.expiry_inspection_assignments ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_assignments_select ON public.expiry_inspection_assignments
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
CREATE POLICY expiry_assignments_write ON public.expiry_inspection_assignments
  FOR ALL TO authenticated
  USING (public.is_org_member(org_id))
  WITH CHECK (public.is_org_member(org_id));

-- ============ Inspection attempts ============

CREATE TABLE IF NOT EXISTS public.expiry_inspection_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  assignment_id UUID NOT NULL REFERENCES public.expiry_inspection_assignments(id) ON DELETE CASCADE,
  parent_attempt_id UUID REFERENCES public.expiry_inspection_attempts(id) ON DELETE SET NULL,
  attempt_number INT NOT NULL DEFAULT 1,
  store_id UUID NOT NULL REFERENCES public.stores(id) ON DELETE CASCADE,
  location_id UUID REFERENCES public.expiry_locations(id) ON DELETE SET NULL,
  sku TEXT NOT NULL DEFAULT '',
  product_name TEXT,
  barcode TEXT,
  inspection_status TEXT NOT NULL DEFAULT 'assigned' CHECK (inspection_status IN (
    'draft', 'assigned', 'in_progress', 'submitted', 'under_review',
    'verified', 'rework_required', 'incomplete', 'cancelled'
  )),
  removal_status TEXT NOT NULL DEFAULT 'not_required' CHECK (removal_status IN (
    'not_required', 'required', 'reported_removed', 'received_quarantine', 'removal_verified'
  )),
  disposition_status TEXT NOT NULL DEFAULT 'not_applicable' CHECK (disposition_status IN (
    'not_applicable', 'pending', 'return_initiated', 'disposal_initiated', 'disposition_verified'
  )),
  sync_status TEXT NOT NULL DEFAULT 'synced' CHECK (sync_status IN (
    'saved_local', 'queued', 'syncing', 'synced', 'failed', 'conflict'
  )),
  auditor_id UUID NOT NULL REFERENCES auth.users(id),
  reviewer_id UUID REFERENCES auth.users(id),
  assurance_level TEXT NOT NULL DEFAULT 'standard',
  assurance_fallback TEXT,
  policy_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  expected_quantity INT NOT NULL DEFAULT 0,
  actual_quantity INT,
  physical_count INT,
  sellable_count INT NOT NULL DEFAULT 0,
  remove_count INT NOT NULL DEFAULT 0,
  unresolved_count INT NOT NULL DEFAULT 0,
  observations_count INT NOT NULL DEFAULT 0,
  quantity_discrepancy_reason TEXT,
  unable_to_inspect_reason TEXT,
  location_coverage JSONB NOT NULL DEFAULT '{}'::jsonb,
  store_fully_checked BOOLEAN NOT NULL DEFAULT false,
  coverage_statement TEXT,
  wizard_step INT NOT NULL DEFAULT 1,
  submitted_at TIMESTAMPTZ,
  verified_at TIMESTAMPTZ,
  verified_by UUID REFERENCES auth.users(id),
  due_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  version INT NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_expiry_attempts_org_status ON public.expiry_inspection_attempts(org_id, inspection_status);
CREATE INDEX IF NOT EXISTS idx_expiry_attempts_auditor ON public.expiry_inspection_attempts(auditor_id, inspection_status);

ALTER TABLE public.expiry_inspection_attempts ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_attempts_select ON public.expiry_inspection_attempts
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
CREATE POLICY expiry_attempts_write ON public.expiry_inspection_attempts
  FOR ALL TO authenticated
  USING (public.is_org_member(org_id))
  WITH CHECK (public.is_org_member(org_id));

-- ============ Stock baseline & movements ============

CREATE TABLE IF NOT EXISTS public.expiry_stock_baselines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  attempt_id UUID NOT NULL REFERENCES public.expiry_inspection_attempts(id) ON DELETE CASCADE,
  source TEXT NOT NULL DEFAULT 'assignment',
  expected_quantity INT NOT NULL DEFAULT 0,
  snapshot_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.expiry_stock_movement_adjustments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  attempt_id UUID NOT NULL REFERENCES public.expiry_inspection_attempts(id) ON DELETE CASCADE,
  adjustment_type TEXT NOT NULL CHECK (adjustment_type IN ('sale', 'receipt', 'transfer', 'other')),
  quantity_delta INT NOT NULL,
  reason TEXT,
  recorded_by UUID REFERENCES auth.users(id),
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.expiry_stock_baselines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.expiry_stock_movement_adjustments ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_baselines_org ON public.expiry_stock_baselines
  FOR ALL TO authenticated USING (public.is_org_member(org_id)) WITH CHECK (public.is_org_member(org_id));
CREATE POLICY expiry_movements_org ON public.expiry_stock_movement_adjustments
  FOR ALL TO authenticated USING (public.is_org_member(org_id)) WITH CHECK (public.is_org_member(org_id));

-- ============ Evidence assets ============

CREATE TABLE IF NOT EXISTS public.expiry_evidence_assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  storage_path TEXT NOT NULL,
  file_hash TEXT NOT NULL,
  perceptual_hash TEXT,
  mime_type TEXT,
  capture_source TEXT NOT NULL DEFAULT 'in_app' CHECK (capture_source IN ('in_app', 'imported', 'live_session')),
  evidence_status TEXT NOT NULL DEFAULT 'uploaded' CHECK (evidence_status IN (
    'pending_upload', 'uploaded', 'processing', 'needs_review', 'accepted', 'rejected'
  )),
  device_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  gps_available BOOLEAN NOT NULL DEFAULT false,
  gps_accuracy_m NUMERIC,
  captured_at TIMESTAMPTZ,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  uploaded_by UUID REFERENCES auth.users(id),
  retention_until TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_expiry_evidence_hash ON public.expiry_evidence_assets(org_id, file_hash);

ALTER TABLE public.expiry_evidence_assets ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_evidence_select ON public.expiry_evidence_assets
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
CREATE POLICY expiry_evidence_insert ON public.expiry_evidence_assets
  FOR INSERT TO authenticated WITH CHECK (public.is_org_member(org_id));

-- ============ Packet observations ============

CREATE TABLE IF NOT EXISTS public.expiry_packet_observations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  attempt_id UUID NOT NULL REFERENCES public.expiry_inspection_attempts(id) ON DELETE CASCADE,
  packet_ordinal INT NOT NULL,
  sku TEXT NOT NULL DEFAULT '',
  raw_date_text TEXT,
  date_type TEXT CHECK (date_type IS NULL OR date_type IN (
    'expiry', 'use_by', 'best_before', 'manufacturing', 'unknown'
  )),
  parsed_date DATE,
  batch_lot TEXT,
  ai_suggested_date DATE,
  ai_confidence NUMERIC,
  ai_simulated BOOLEAN NOT NULL DEFAULT false,
  human_confirmed_date DATE,
  human_correction TEXT,
  classification TEXT NOT NULL DEFAULT 'unresolved' CHECK (classification IN (
    'sellable', 'near_expiry', 'expired', 'unresolved'
  )),
  placement TEXT CHECK (placement IS NULL OR placement IN ('sellable', 'remove', 'unresolved')),
  duplicate_hash_flag BOOLEAN NOT NULL DEFAULT false,
  similarity_flag BOOLEAN NOT NULL DEFAULT false,
  wrong_product BOOLEAN NOT NULL DEFAULT false,
  unreadable BOOLEAN NOT NULL DEFAULT false,
  review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN (
    'pending', 'accepted', 'retake_requested', 'returned'
  )),
  created_by UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (attempt_id, packet_ordinal)
);

ALTER TABLE public.expiry_packet_observations ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_observations_org ON public.expiry_packet_observations
  FOR ALL TO authenticated USING (public.is_org_member(org_id)) WITH CHECK (public.is_org_member(org_id));

-- ============ Evidence links ============

CREATE TABLE IF NOT EXISTS public.expiry_evidence_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  evidence_id UUID NOT NULL REFERENCES public.expiry_evidence_assets(id) ON DELETE CASCADE,
  attempt_id UUID REFERENCES public.expiry_inspection_attempts(id) ON DELETE CASCADE,
  observation_id UUID REFERENCES public.expiry_packet_observations(id) ON DELETE CASCADE,
  link_type TEXT NOT NULL CHECK (link_type IN (
    'context', 'packet_date', 'quarantine_contents', 'quarantine_seal', 'live_session'
  )),
  session_timestamp_ms BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.expiry_evidence_links ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_evidence_links_org ON public.expiry_evidence_links
  FOR ALL TO authenticated USING (public.is_org_member(org_id)) WITH CHECK (public.is_org_member(org_id));

-- ============ Review decisions ============

CREATE TABLE IF NOT EXISTS public.expiry_review_decisions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  attempt_id UUID NOT NULL REFERENCES public.expiry_inspection_attempts(id) ON DELETE CASCADE,
  observation_id UUID REFERENCES public.expiry_packet_observations(id) ON DELETE CASCADE,
  decision_type TEXT NOT NULL CHECK (decision_type IN (
    'accept', 'retake', 'recount', 'return', 'verify_inspection', 'verify_removal', 'comment', 'assign_recheck'
  )),
  comment TEXT,
  decided_by UUID NOT NULL REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.expiry_review_decisions ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_review_decisions_org ON public.expiry_review_decisions
  FOR ALL TO authenticated USING (public.is_org_member(org_id)) WITH CHECK (public.is_org_member(org_id));

-- ============ Exceptions (action required) ============

CREATE TABLE IF NOT EXISTS public.expiry_exceptions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  attempt_id UUID REFERENCES public.expiry_inspection_attempts(id) ON DELETE SET NULL,
  observation_id UUID REFERENCES public.expiry_packet_observations(id) ON DELETE SET NULL,
  store_id UUID REFERENCES public.stores(id) ON DELETE SET NULL,
  location_id UUID REFERENCES public.expiry_locations(id) ON DELETE SET NULL,
  sku TEXT,
  issue_type TEXT NOT NULL CHECK (issue_type IN (
    'expired_not_quarantined', 'unresolved_not_held', 'rejected_evidence', 'quantity_mismatch',
    'duplicate_evidence', 'overdue_inspection', 'near_expiry_action', 'receipt_mismatch', 'other'
  )),
  severity TEXT NOT NULL DEFAULT 'medium' CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  title TEXT NOT NULL,
  quantity INT NOT NULL DEFAULT 0,
  owner_id UUID REFERENCES auth.users(id),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved', 'dismissed')),
  due_at TIMESTAMPTZ,
  sort_priority INT NOT NULL DEFAULT 100,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.expiry_exceptions ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_exceptions_org ON public.expiry_exceptions
  FOR ALL TO authenticated USING (public.is_org_member(org_id)) WITH CHECK (public.is_org_member(org_id));

-- ============ Quarantine ============

CREATE TABLE IF NOT EXISTS public.expiry_quarantine_containers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  store_id UUID NOT NULL REFERENCES public.stores(id) ON DELETE CASCADE,
  container_code TEXT NOT NULL,
  quarantine_location TEXT NOT NULL,
  seal_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, container_code)
);

CREATE TABLE IF NOT EXISTS public.expiry_quarantine_transfers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  attempt_id UUID NOT NULL REFERENCES public.expiry_inspection_attempts(id) ON DELETE CASCADE,
  container_id UUID NOT NULL REFERENCES public.expiry_quarantine_containers(id) ON DELETE CASCADE,
  removal_reason TEXT NOT NULL CHECK (removal_reason IN ('expired', 'pending_date_review', 'near_expiry_hold', 'other')),
  sku TEXT NOT NULL,
  quantity INT NOT NULL,
  sender_id UUID NOT NULL REFERENCES auth.users(id),
  receiver_id UUID REFERENCES auth.users(id),
  transfer_status TEXT NOT NULL DEFAULT 'reported' CHECK (transfer_status IN (
    'reported', 'received', 'mismatch', 'rejected', 'verified'
  )),
  transferred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.expiry_quarantine_receipts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  transfer_id UUID NOT NULL REFERENCES public.expiry_quarantine_transfers(id) ON DELETE CASCADE,
  receiver_id UUID NOT NULL REFERENCES auth.users(id),
  received_quantity INT NOT NULL,
  mismatch_quantity INT,
  mismatch_reason TEXT,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.expiry_disposition_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  transfer_id UUID NOT NULL REFERENCES public.expiry_quarantine_transfers(id) ON DELETE CASCADE,
  action_type TEXT NOT NULL CHECK (action_type IN ('supplier_return', 'disposal', 'authorized_release')),
  owner_id UUID REFERENCES auth.users(id),
  due_at TIMESTAMPTZ,
  disposition_status TEXT NOT NULL DEFAULT 'pending' CHECK (disposition_status IN (
    'pending', 'return_initiated', 'disposal_initiated', 'disposition_verified'
  )),
  pos_integration_status TEXT NOT NULL DEFAULT 'not_configured' CHECK (pos_integration_status IN (
    'not_configured', 'pending', 'confirmed', 'failed'
  )),
  verified_by UUID REFERENCES auth.users(id),
  verified_at TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.expiry_quarantine_containers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.expiry_quarantine_transfers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.expiry_quarantine_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.expiry_disposition_actions ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_quarantine_containers_org ON public.expiry_quarantine_containers
  FOR ALL TO authenticated USING (public.is_org_member(org_id)) WITH CHECK (public.is_org_member(org_id));
CREATE POLICY expiry_quarantine_transfers_org ON public.expiry_quarantine_transfers
  FOR ALL TO authenticated USING (public.is_org_member(org_id)) WITH CHECK (public.is_org_member(org_id));
CREATE POLICY expiry_quarantine_receipts_org ON public.expiry_quarantine_receipts
  FOR ALL TO authenticated USING (public.is_org_member(org_id)) WITH CHECK (public.is_org_member(org_id));
CREATE POLICY expiry_disposition_actions_org ON public.expiry_disposition_actions
  FOR ALL TO authenticated USING (public.is_org_member(org_id)) WITH CHECK (public.is_org_member(org_id));

-- ============ Recheck & future actions ============

CREATE TABLE IF NOT EXISTS public.expiry_recheck_assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  original_attempt_id UUID NOT NULL REFERENCES public.expiry_inspection_attempts(id) ON DELETE CASCADE,
  new_attempt_id UUID REFERENCES public.expiry_inspection_attempts(id) ON DELETE SET NULL,
  assigned_to UUID NOT NULL REFERENCES auth.users(id),
  reason TEXT,
  created_by UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.expiry_future_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  store_id UUID REFERENCES public.stores(id) ON DELETE CASCADE,
  sku TEXT,
  action_type TEXT NOT NULL CHECK (action_type IN (
    'next_inspection', 'approaching_threshold', 'fefo_replenishment', 'markdown', 'supplier_return'
  )),
  due_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'completed', 'cancelled')),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.expiry_recheck_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.expiry_future_actions ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_recheck_org ON public.expiry_recheck_assignments
  FOR ALL TO authenticated USING (public.is_org_member(org_id)) WITH CHECK (public.is_org_member(org_id));
CREATE POLICY expiry_future_actions_org ON public.expiry_future_actions
  FOR ALL TO authenticated USING (public.is_org_member(org_id)) WITH CHECK (public.is_org_member(org_id));

-- ============ Audit events & idempotency ============

CREATE TABLE IF NOT EXISTS public.expiry_audit_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id UUID NOT NULL,
  action TEXT NOT NULL,
  actor_id UUID REFERENCES auth.users(id),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.expiry_idempotency_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  user_id UUID NOT NULL REFERENCES auth.users(id),
  idempotency_key TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  result JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (org_id, user_id, idempotency_key)
);

ALTER TABLE public.expiry_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.expiry_idempotency_keys ENABLE ROW LEVEL SECURITY;
CREATE POLICY expiry_audit_events_select ON public.expiry_audit_events
  FOR SELECT TO authenticated USING (public.is_org_member(org_id));
CREATE POLICY expiry_idempotency_org ON public.expiry_idempotency_keys
  FOR ALL TO authenticated USING (public.is_org_member(org_id)) WITH CHECK (public.is_org_member(org_id));

-- ============ Helper functions ============

CREATE OR REPLACE FUNCTION public.expiry_is_reviewer(p_org_id UUID, p_user_id UUID)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT public.is_org_manager(p_org_id)
    OR EXISTS (
      SELECT 1 FROM public.expiry_role_grants g
      WHERE g.org_id = p_org_id AND g.user_id = p_user_id AND g.grant_role IN ('reviewer', 'admin')
    );
$$;

CREATE OR REPLACE FUNCTION public.expiry_is_supervisor(p_org_id UUID, p_user_id UUID, p_store_id UUID DEFAULT NULL)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT public.is_org_manager(p_org_id)
    OR EXISTS (
      SELECT 1 FROM public.expiry_role_grants g
      WHERE g.org_id = p_org_id AND g.user_id = p_user_id
        AND g.grant_role IN ('supervisor', 'admin')
        AND (g.store_id IS NULL OR g.store_id = p_store_id)
    );
$$;

CREATE OR REPLACE FUNCTION public.expiry_demo_clock()
RETURNS TIMESTAMPTZ
LANGUAGE sql STABLE AS $$
  SELECT COALESCE(
    NULLIF(current_setting('expiry.demo_clock', true), '')::timestamptz,
    now()
  );
$$;

-- ============ Reconciliation check ============

CREATE OR REPLACE FUNCTION public.expiry_reconciliation_ok(p_attempt_id UUID)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT COALESCE(
    (SELECT a.physical_count = (a.sellable_count + a.remove_count + a.unresolved_count)
       AND a.observations_count = a.physical_count
       AND a.physical_count IS NOT NULL
     FROM public.expiry_inspection_attempts a WHERE a.id = p_attempt_id),
    false
  );
$$;

-- ============ Core transition RPC ============

CREATE OR REPLACE FUNCTION public.expiry_transition(
  p_entity_type TEXT,
  p_entity_id UUID,
  p_action TEXT,
  p_payload JSONB DEFAULT '{}'::jsonb,
  p_idempotency_key TEXT DEFAULT NULL
)
RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_user UUID := auth.uid();
  v_org UUID;
  v_attempt public.expiry_inspection_attempts%ROWTYPE;
  v_obs public.expiry_packet_observations%ROWTYPE;
  v_transfer public.expiry_quarantine_transfers%ROWTYPE;
  v_cached JSONB;
  v_hash TEXT;
  v_dup_count INT;
  v_classification TEXT;
  v_near_days INT := 7;
BEGIN
  IF v_user IS NULL THEN
    RAISE EXCEPTION 'Authentication required';
  END IF;

  IF p_idempotency_key IS NOT NULL THEN
    SELECT result INTO v_cached
    FROM public.expiry_idempotency_keys
    WHERE org_id = COALESCE(v_org, (SELECT org_id FROM public.expiry_inspection_attempts WHERE id = p_entity_id LIMIT 1))
      AND user_id = v_user AND idempotency_key = p_idempotency_key;
    IF v_cached IS NOT NULL THEN RETURN v_cached; END IF;
  END IF;

  -- Attempt-scoped actions
  IF p_entity_type = 'attempt' THEN
    SELECT * INTO v_attempt FROM public.expiry_inspection_attempts WHERE id = p_entity_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Attempt not found'; END IF;
    v_org := v_attempt.org_id;
    IF NOT public.is_org_member(v_org) THEN RAISE EXCEPTION 'Access denied'; END IF;

    CASE p_action
      WHEN 'start' THEN
        IF v_attempt.auditor_id <> v_user AND NOT public.is_org_manager(v_org) THEN
          RAISE EXCEPTION 'Only assigned auditor can start';
        END IF;
        UPDATE public.expiry_inspection_attempts
        SET inspection_status = 'in_progress', wizard_step = 1, updated_at = now()
        WHERE id = p_entity_id;

      WHEN 'confirm_scope' THEN
        IF v_attempt.auditor_id <> v_user THEN RAISE EXCEPTION 'Only assigned auditor'; END IF;
        UPDATE public.expiry_inspection_attempts SET
          actual_quantity = COALESCE((p_payload->>'actual_quantity')::int, actual_quantity),
          physical_count = COALESCE((p_payload->>'physical_count')::int, physical_count),
          quantity_discrepancy_reason = NULLIF(p_payload->>'quantity_discrepancy_reason', ''),
          wizard_step = GREATEST(wizard_step, 2),
          inspection_status = 'in_progress',
          updated_at = now(),
          version = version + 1
        WHERE id = p_entity_id;

      WHEN 'set_assurance_fallback' THEN
        UPDATE public.expiry_inspection_attempts SET
          assurance_fallback = NULLIF(p_payload->>'assurance_fallback', ''),
          updated_at = now()
        WHERE id = p_entity_id;

      WHEN 'record_observation' THEN
        IF v_attempt.auditor_id <> v_user THEN RAISE EXCEPTION 'Only assigned auditor'; END IF;
        v_hash := NULLIF(p_payload->>'file_hash', '');
        IF v_hash IS NOT NULL THEN
          SELECT COUNT(*) INTO v_dup_count
          FROM public.expiry_evidence_assets ea
          JOIN public.expiry_evidence_links el ON el.evidence_id = ea.id
          WHERE ea.org_id = v_org AND ea.file_hash = v_hash
            AND el.observation_id IS NOT NULL
            AND el.attempt_id = p_entity_id
            AND (p_payload->>'observation_id') IS NOT NULL
            AND el.observation_id <> (p_payload->>'observation_id')::uuid;
          IF v_dup_count > 0 THEN
            RAISE EXCEPTION 'Duplicate evidence file for this inspection';
          END IF;
        END IF;

        v_classification := COALESCE(NULLIF(p_payload->>'classification', ''), 'unresolved');
        IF COALESCE((p_payload->>'unreadable')::boolean, false) AND v_classification = 'sellable' THEN
          RAISE EXCEPTION 'Unreadable dates cannot be marked sellable';
        END IF;

        INSERT INTO public.expiry_packet_observations (
          org_id, attempt_id, packet_ordinal, sku, raw_date_text, date_type, parsed_date,
          batch_lot, ai_suggested_date, ai_confidence, ai_simulated, human_confirmed_date,
          human_correction, classification, placement, duplicate_hash_flag, unreadable, wrong_product, created_by
        ) VALUES (
          v_org, p_entity_id,
          COALESCE((p_payload->>'packet_ordinal')::int, 1),
          COALESCE(NULLIF(p_payload->>'sku', ''), v_attempt.sku),
          NULLIF(p_payload->>'raw_date_text', ''),
          NULLIF(p_payload->>'date_type', ''),
          NULLIF(p_payload->>'parsed_date', '')::date,
          NULLIF(p_payload->>'batch_lot', ''),
          NULLIF(p_payload->>'ai_suggested_date', '')::date,
          NULLIF(p_payload->>'ai_confidence', '')::numeric,
          COALESCE((p_payload->>'ai_simulated')::boolean, false),
          NULLIF(p_payload->>'human_confirmed_date', '')::date,
          NULLIF(p_payload->>'human_correction', ''),
          v_classification,
          NULLIF(p_payload->>'placement', ''),
          COALESCE((p_payload->>'duplicate_hash_flag')::boolean, false),
          COALESCE((p_payload->>'unreadable')::boolean, false),
          COALESCE((p_payload->>'wrong_product')::boolean, false),
          v_user
        )
        ON CONFLICT (attempt_id, packet_ordinal) DO UPDATE SET
          raw_date_text = EXCLUDED.raw_date_text,
          date_type = EXCLUDED.date_type,
          parsed_date = EXCLUDED.parsed_date,
          batch_lot = EXCLUDED.batch_lot,
          ai_suggested_date = EXCLUDED.ai_suggested_date,
          ai_confidence = EXCLUDED.ai_confidence,
          ai_simulated = EXCLUDED.ai_simulated,
          human_confirmed_date = EXCLUDED.human_confirmed_date,
          human_correction = EXCLUDED.human_correction,
          classification = EXCLUDED.classification,
          placement = EXCLUDED.placement,
          duplicate_hash_flag = EXCLUDED.duplicate_hash_flag,
          unreadable = EXCLUDED.unreadable,
          wrong_product = EXCLUDED.wrong_product,
          updated_at = now();

        UPDATE public.expiry_inspection_attempts SET
          sellable_count = (SELECT COUNT(*) FROM public.expiry_packet_observations WHERE attempt_id = p_entity_id AND classification = 'sellable'),
          remove_count = (SELECT COUNT(*) FROM public.expiry_packet_observations WHERE attempt_id = p_entity_id AND classification IN ('expired', 'near_expiry')),
          unresolved_count = (SELECT COUNT(*) FROM public.expiry_packet_observations WHERE attempt_id = p_entity_id AND classification = 'unresolved'),
          observations_count = (SELECT COUNT(*) FROM public.expiry_packet_observations WHERE attempt_id = p_entity_id),
          wizard_step = GREATEST(wizard_step, 3),
          updated_at = now(),
          version = version + 1
        WHERE id = p_entity_id;

        SELECT * INTO v_attempt FROM public.expiry_inspection_attempts WHERE id = p_entity_id;
        IF v_attempt.remove_count + v_attempt.unresolved_count > 0 THEN
          UPDATE public.expiry_inspection_attempts SET removal_status = 'required' WHERE id = p_entity_id;
        END IF;

      WHEN 'reconcile' THEN
        IF v_attempt.auditor_id <> v_user THEN RAISE EXCEPTION 'Only assigned auditor'; END IF;
        IF NOT public.expiry_reconciliation_ok(p_entity_id) THEN
          RAISE EXCEPTION 'Quantity reconciliation failed: physical count must equal sellable + remove + unresolved and match observations';
        END IF;
        UPDATE public.expiry_inspection_attempts SET wizard_step = 5, updated_at = now(), version = version + 1
        WHERE id = p_entity_id;

      WHEN 'submit' THEN
        IF v_attempt.auditor_id <> v_user THEN RAISE EXCEPTION 'Only assigned auditor'; END IF;
        UPDATE public.expiry_inspection_attempts SET
          inspection_status = 'submitted',
          submitted_at = now(),
          updated_at = now(),
          version = version + 1
        WHERE id = p_entity_id;
        PERFORM public.sync_expiry_findings(p_entity_id);

      WHEN 'submit_incomplete' THEN
        IF v_attempt.auditor_id <> v_user THEN RAISE EXCEPTION 'Only assigned auditor'; END IF;
        UPDATE public.expiry_inspection_attempts SET
          inspection_status = 'incomplete',
          unable_to_inspect_reason = NULLIF(p_payload->>'reason', ''),
          submitted_at = now(),
          updated_at = now(),
          version = version + 1
        WHERE id = p_entity_id;
        PERFORM public.sync_expiry_findings(p_entity_id);

      WHEN 'verify_inspection' THEN
        IF NOT public.expiry_is_reviewer(v_org, v_user) THEN RAISE EXCEPTION 'Reviewer permission required'; END IF;
        IF v_attempt.auditor_id = v_user THEN RAISE EXCEPTION 'Self-approval denied'; END IF;
        IF NOT public.expiry_reconciliation_ok(p_entity_id) AND v_attempt.inspection_status <> 'incomplete' THEN
          RAISE EXCEPTION 'Cannot verify: reconciliation incomplete';
        END IF;
        UPDATE public.expiry_inspection_attempts SET
          inspection_status = 'verified',
          verified_at = now(),
          verified_by = v_user,
          updated_at = now(),
          version = version + 1
        WHERE id = p_entity_id;

      WHEN 'report_quarantine_transfer' THEN
        IF v_attempt.auditor_id <> v_user THEN RAISE EXCEPTION 'Only assigned auditor'; END IF;
        UPDATE public.expiry_inspection_attempts SET
          removal_status = 'reported_removed',
          updated_at = now(),
          version = version + 1
        WHERE id = p_entity_id;

      ELSE
        RAISE EXCEPTION 'Unknown attempt action: %', p_action;
    END CASE;

  ELSIF p_entity_type = 'transfer' THEN
    SELECT * INTO v_transfer FROM public.expiry_quarantine_transfers WHERE id = p_entity_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Transfer not found'; END IF;
    v_org := v_transfer.org_id;

    CASE p_action
      WHEN 'confirm_receipt' THEN
        IF v_transfer.sender_id = v_user THEN RAISE EXCEPTION 'Self-confirmation of quarantine receipt denied'; END IF;
        IF NOT public.expiry_is_supervisor(v_org, v_user, (SELECT store_id FROM public.expiry_inspection_attempts WHERE id = v_transfer.attempt_id)) THEN
          RAISE EXCEPTION 'Supervisor permission required';
        END IF;
        INSERT INTO public.expiry_quarantine_receipts (org_id, transfer_id, receiver_id, received_quantity)
        VALUES (v_org, p_entity_id, v_user, COALESCE((p_payload->>'received_quantity')::int, v_transfer.quantity));
        UPDATE public.expiry_quarantine_transfers SET transfer_status = 'received' WHERE id = p_entity_id;
        UPDATE public.expiry_inspection_attempts SET removal_status = 'received_quarantine'
        WHERE id = v_transfer.attempt_id;

      WHEN 'report_mismatch' THEN
        IF v_transfer.sender_id = v_user THEN RAISE EXCEPTION 'Self-confirmation denied'; END IF;
        INSERT INTO public.expiry_quarantine_receipts (org_id, transfer_id, receiver_id, received_quantity, mismatch_quantity, mismatch_reason)
        VALUES (v_org, p_entity_id, v_user,
          COALESCE((p_payload->>'received_quantity')::int, 0),
          COALESCE((p_payload->>'mismatch_quantity')::int, 0),
          NULLIF(p_payload->>'mismatch_reason', ''));
        UPDATE public.expiry_quarantine_transfers SET transfer_status = 'mismatch' WHERE id = p_entity_id;
        INSERT INTO public.expiry_exceptions (org_id, attempt_id, issue_type, severity, title, quantity, sort_priority)
        VALUES (v_org, v_transfer.attempt_id, 'receipt_mismatch', 'critical', 'Quarantine receipt quantity mismatch', v_transfer.quantity, 4);

      WHEN 'verify_removal' THEN
        IF NOT public.expiry_is_reviewer(v_org, v_user) THEN RAISE EXCEPTION 'Reviewer required'; END IF;
        UPDATE public.expiry_quarantine_transfers SET transfer_status = 'verified' WHERE id = p_entity_id;
        UPDATE public.expiry_inspection_attempts SET removal_status = 'removal_verified'
        WHERE id = v_transfer.attempt_id;

      ELSE
        RAISE EXCEPTION 'Unknown transfer action: %', p_action;
    END CASE;

  ELSIF p_entity_type = 'observation' THEN
    SELECT * INTO v_obs FROM public.expiry_packet_observations WHERE id = p_entity_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Observation not found'; END IF;
    v_org := v_obs.org_id;
    IF NOT public.expiry_is_reviewer(v_org, v_user) THEN RAISE EXCEPTION 'Reviewer required'; END IF;

    CASE p_action
      WHEN 'accept' THEN
        UPDATE public.expiry_packet_observations SET review_status = 'accepted', updated_at = now() WHERE id = p_entity_id;
      WHEN 'request_retake' THEN
        UPDATE public.expiry_packet_observations SET review_status = 'retake_requested', updated_at = now() WHERE id = p_entity_id;
      ELSE
        RAISE EXCEPTION 'Unknown observation action: %', p_action;
    END CASE;
  ELSE
    RAISE EXCEPTION 'Unknown entity type: %', p_entity_type;
  END IF;

  INSERT INTO public.expiry_audit_events (org_id, entity_type, entity_id, action, actor_id, payload)
  VALUES (v_org, p_entity_type, p_entity_id, p_action, v_user, p_payload);

  v_cached := jsonb_build_object('ok', true, 'entity_type', p_entity_type, 'entity_id', p_entity_id, 'action', p_action);

  IF p_idempotency_key IS NOT NULL THEN
    INSERT INTO public.expiry_idempotency_keys (org_id, user_id, idempotency_key, entity_type, result)
    VALUES (v_org, v_user, p_idempotency_key, p_entity_type, v_cached)
    ON CONFLICT (org_id, user_id, idempotency_key) DO NOTHING;
  END IF;

  RETURN v_cached;
END;
$$;

GRANT EXECUTE ON FUNCTION public.expiry_transition TO authenticated;
GRANT EXECUTE ON FUNCTION public.expiry_reconciliation_ok TO authenticated;
GRANT EXECUTE ON FUNCTION public.expiry_is_reviewer TO authenticated;
GRANT EXECUTE ON FUNCTION public.expiry_is_supervisor TO authenticated;
GRANT EXECUTE ON FUNCTION public.expiry_demo_clock TO authenticated;

-- ============ Sync urgent findings ============

CREATE OR REPLACE FUNCTION public.sync_expiry_findings(p_attempt_id UUID)
RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_attempt public.expiry_inspection_attempts%ROWTYPE;
  v_expired INT;
  v_unresolved INT;
BEGIN
  SELECT * INTO v_attempt FROM public.expiry_inspection_attempts WHERE id = p_attempt_id;
  IF NOT FOUND THEN RETURN; END IF;

  SELECT COUNT(*) INTO v_expired FROM public.expiry_packet_observations
  WHERE attempt_id = p_attempt_id AND classification = 'expired';
  SELECT COUNT(*) INTO v_unresolved FROM public.expiry_packet_observations
  WHERE attempt_id = p_attempt_id AND classification = 'unresolved';

  IF v_expired > 0 AND v_attempt.removal_status IN ('not_required', 'required') THEN
    INSERT INTO public.expiry_exceptions (org_id, attempt_id, store_id, sku, issue_type, severity, title, quantity, sort_priority)
    SELECT v_attempt.org_id, p_attempt_id, v_attempt.store_id, v_attempt.sku,
      'expired_not_quarantined', 'critical',
      'Expired stock not yet confirmed in quarantine', v_expired, 1
    WHERE NOT EXISTS (
      SELECT 1 FROM public.expiry_exceptions e
      WHERE e.attempt_id = p_attempt_id AND e.issue_type = 'expired_not_quarantined' AND e.status = 'open'
    );
  END IF;

  IF v_unresolved > 0 THEN
    INSERT INTO public.expiry_exceptions (org_id, attempt_id, store_id, sku, issue_type, severity, title, quantity, sort_priority)
    SELECT v_attempt.org_id, p_attempt_id, v_attempt.store_id, v_attempt.sku,
      'unresolved_not_held', 'high',
      'Unresolved dates awaiting hold/review', v_unresolved, 2
    WHERE NOT EXISTS (
      SELECT 1 FROM public.expiry_exceptions e
      WHERE e.attempt_id = p_attempt_id AND e.issue_type = 'unresolved_not_held' AND e.status = 'open'
    );
  END IF;

  IF v_attempt.actual_quantity IS NOT NULL AND v_attempt.expected_quantity <> v_attempt.actual_quantity THEN
    INSERT INTO public.expiry_exceptions (org_id, attempt_id, store_id, sku, issue_type, severity, title, quantity, sort_priority)
    SELECT v_attempt.org_id, p_attempt_id, v_attempt.store_id, v_attempt.sku,
      'quantity_mismatch', 'high',
      'Expected vs actual quantity mismatch', ABS(v_attempt.actual_quantity - v_attempt.expected_quantity), 4
    WHERE NOT EXISTS (
      SELECT 1 FROM public.expiry_exceptions e
      WHERE e.attempt_id = p_attempt_id AND e.issue_type = 'quantity_mismatch' AND e.status = 'open'
    );
  END IF;
END;
$$;

GRANT EXECUTE ON FUNCTION public.sync_expiry_findings TO authenticated;

-- ============ Overview metrics RPC ============

CREATE OR REPLACE FUNCTION public.expiry_overview_metrics(p_org_id UUID, p_store_id UUID DEFAULT NULL)
RETURNS JSONB
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT jsonb_build_object(
    'units_in_scope', COALESCE((
      SELECT SUM(expected_quantity)::int FROM public.expiry_inspection_attempts
      WHERE org_id = p_org_id AND inspection_status IN ('assigned','in_progress','submitted','under_review')
        AND (p_store_id IS NULL OR store_id = p_store_id)
    ), 0),
    'units_inspected', COALESCE((
      SELECT SUM(observations_count)::int FROM public.expiry_inspection_attempts
      WHERE org_id = p_org_id AND observations_count > 0
        AND (p_store_id IS NULL OR store_id = p_store_id)
    ), 0),
    'expired_detected', COALESCE((
      SELECT SUM(CASE WHEN classification = 'expired' THEN 1 ELSE 0 END)::int
      FROM public.expiry_packet_observations o
      JOIN public.expiry_inspection_attempts a ON a.id = o.attempt_id
      WHERE o.org_id = p_org_id AND (p_store_id IS NULL OR a.store_id = p_store_id)
    ), 0),
    'near_expiry', COALESCE((
      SELECT SUM(CASE WHEN classification = 'near_expiry' THEN 1 ELSE 0 END)::int
      FROM public.expiry_packet_observations o
      JOIN public.expiry_inspection_attempts a ON a.id = o.attempt_id
      WHERE o.org_id = p_org_id AND (p_store_id IS NULL OR a.store_id = p_store_id)
    ), 0),
    'unresolved_dates', COALESCE((
      SELECT SUM(CASE WHEN classification = 'unresolved' OR unreadable THEN 1 ELSE 0 END)::int
      FROM public.expiry_packet_observations o
      JOIN public.expiry_inspection_attempts a ON a.id = o.attempt_id
      WHERE o.org_id = p_org_id AND (p_store_id IS NULL OR a.store_id = p_store_id)
    ), 0),
    'awaiting_removal_verification', COALESCE((
      SELECT COUNT(*)::int FROM public.expiry_inspection_attempts
      WHERE org_id = p_org_id AND removal_status = 'reported_removed'
        AND (p_store_id IS NULL OR store_id = p_store_id)
    ), 0),
    'in_quarantine', COALESCE((
      SELECT COUNT(*)::int FROM public.expiry_inspection_attempts
      WHERE org_id = p_org_id AND removal_status = 'received_quarantine'
        AND (p_store_id IS NULL OR store_id = p_store_id)
    ), 0),
    'disposition_pending', COALESCE((
      SELECT COUNT(*)::int FROM public.expiry_disposition_actions d
      JOIN public.expiry_quarantine_transfers t ON t.id = d.transfer_id
      JOIN public.expiry_inspection_attempts a ON a.id = t.attempt_id
      WHERE d.org_id = p_org_id AND d.disposition_status IN ('pending','return_initiated','disposal_initiated')
        AND (p_store_id IS NULL OR a.store_id = p_store_id)
    ), 0),
    'overdue_inspections', COALESCE((
      SELECT COUNT(*)::int FROM public.expiry_inspection_attempts
      WHERE org_id = p_org_id AND due_at < now()
        AND inspection_status IN ('assigned','in_progress')
        AND (p_store_id IS NULL OR store_id = p_store_id)
    ), 0),
    'open_exceptions', COALESCE((
      SELECT COUNT(*)::int FROM public.expiry_exceptions
      WHERE org_id = p_org_id AND status = 'open'
        AND (p_store_id IS NULL OR store_id = p_store_id)
    ), 0),
    'refreshed_at', now()
  );
$$;

GRANT EXECUTE ON FUNCTION public.expiry_overview_metrics TO authenticated;

-- Extend findings finding_type for near_expiry
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'findings_finding_type_check'
  ) THEN
    ALTER TABLE public.findings DROP CONSTRAINT findings_finding_type_check;
  END IF;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;

ALTER TABLE public.findings ADD CONSTRAINT findings_finding_type_check
  CHECK (finding_type IN (
    'inventory_shortage', 'inventory_excess', 'out_of_stock', 'wrong_placement',
    'planogram_violation', 'pricing_issue', 'damaged_product', 'expired_product',
    'near_expiry', 'missing_product', 'receiving_issue', 'display_issue',
    'shelf_execution_issue', 'other'
  ));

-- ============ Demo seed (development only) ============

CREATE OR REPLACE FUNCTION public.seed_expiry_demo_scenario(p_org_id UUID, p_user_id UUID)
RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_store UUID;
  v_policy UUID;
  v_loc_shelf UUID;
  v_loc_back UUID;
  v_assignment UUID;
  v_attempt UUID;
  v_transfer UUID;
  v_clock DATE := public.expiry_demo_clock()::date;
BEGIN
  IF NOT public.is_org_manager(p_org_id) THEN
    RAISE EXCEPTION 'Admin/manager required to seed demo data';
  END IF;

  SELECT id INTO v_store FROM public.stores WHERE org_id = p_org_id ORDER BY created_at LIMIT 1;
  IF v_store IS NULL THEN RAISE EXCEPTION 'No store found for org'; END IF;

  INSERT INTO public.expiry_policy_versions (org_id, name, version, status, rules, near_expiry_days, published_at, created_by)
  VALUES (p_org_id, 'Default Expiry Policy', 1, 'published', '{"label":"demo"}'::jsonb, 7, now(), p_user_id)
  ON CONFLICT (org_id, name, version) DO UPDATE SET status = 'published'
  RETURNING id INTO v_policy;

  INSERT INTO public.expiry_locations (org_id, store_id, location_type, label)
  VALUES (p_org_id, v_store, 'main_shelf', 'Main shelf')
  ON CONFLICT (org_id, store_id, label) DO UPDATE SET is_active = true
  RETURNING id INTO v_loc_shelf;

  INSERT INTO public.expiry_locations (org_id, store_id, location_type, label)
  VALUES (p_org_id, v_store, 'backroom', 'Backroom')
  ON CONFLICT (org_id, store_id, label) DO UPDATE SET is_active = true
  RETURNING id INTO v_loc_back;

  INSERT INTO public.expiry_inspection_assignments (
    org_id, store_id, title, status, location_ids, required_location_ids,
    sku_filters, auditor_id, reviewer_id, due_at, policy_version_id, policy_snapshot,
    instructions, created_by
  ) VALUES (
    p_org_id, v_store, 'Maggi expiry check — Main shelf', 'assigned',
    ARRAY[v_loc_shelf], ARRAY[v_loc_shelf, v_loc_back],
    '{"sku":"MAGGI-70G"}'::jsonb, p_user_id, p_user_id,
    now() + interval '2 days', v_policy, '{"near_expiry_days":7}'::jsonb,
    'Inspect all visible Maggi 70g packets. Backroom still outstanding.', p_user_id
  ) RETURNING id INTO v_assignment;

  INSERT INTO public.expiry_inspection_attempts (
    org_id, assignment_id, store_id, location_id, sku, product_name,
    inspection_status, removal_status, auditor_id, expected_quantity, actual_quantity,
    physical_count, sellable_count, remove_count, unresolved_count, observations_count,
    policy_snapshot, location_coverage, store_fully_checked, coverage_statement, due_at
  ) VALUES (
    p_org_id, v_assignment, v_store, v_loc_shelf, 'MAGGI-70G', 'Maggi 2-Minute Noodles 70g',
    'submitted', 'reported_removed', p_user_id, 4, 4, 4, 2, 1, 1, 4,
    '{"near_expiry_days":7}'::jsonb,
    jsonb_build_object(v_loc_shelf::text, true, v_loc_back::text, false),
    false, 'Main shelf verified; backroom not inspected — not a store-wide clearance.',
    now() + interval '1 day'
  ) RETURNING id INTO v_attempt;

  INSERT INTO public.expiry_packet_observations (
    org_id, attempt_id, packet_ordinal, sku, parsed_date, human_confirmed_date,
    classification, placement, ai_simulated, ai_confidence, date_type
  ) VALUES
    (p_org_id, v_attempt, 1, 'MAGGI-70G', v_clock + 60, v_clock + 60, 'sellable', 'sellable', true, 0.82, 'expiry'),
    (p_org_id, v_attempt, 2, 'MAGGI-70G', v_clock + 45, v_clock + 45, 'sellable', 'sellable', true, 0.85, 'expiry'),
    (p_org_id, v_attempt, 3, 'MAGGI-70G', v_clock - 10, v_clock - 10, 'expired', 'remove', true, 0.79, 'expiry'),
    (p_org_id, v_attempt, 4, 'MAGGI-70G', NULL, NULL, 'unresolved', 'unresolved', false, NULL, 'unknown');

  UPDATE public.expiry_packet_observations SET unreadable = true WHERE attempt_id = v_attempt AND packet_ordinal = 4;

  INSERT INTO public.expiry_quarantine_containers (org_id, store_id, container_code, quarantine_location)
  VALUES (p_org_id, v_store, 'Q-BAG-001', 'Returns holding area')
  ON CONFLICT (org_id, container_code) DO NOTHING;

  INSERT INTO public.expiry_quarantine_transfers (
    org_id, attempt_id, container_id, removal_reason, sku, quantity, sender_id, transfer_status
  )
  SELECT p_org_id, v_attempt, c.id, 'expired', 'MAGGI-70G', 2, p_user_id, 'reported'
  FROM public.expiry_quarantine_containers c
  WHERE c.org_id = p_org_id AND c.container_code = 'Q-BAG-001'
  RETURNING id INTO v_transfer;

  INSERT INTO public.expiry_exceptions (org_id, attempt_id, store_id, location_id, sku, issue_type, severity, title, quantity, sort_priority)
  VALUES
    (p_org_id, v_attempt, v_store, v_loc_shelf, 'MAGGI-70G', 'expired_not_quarantined', 'critical', 'Expired stock awaiting quarantine receipt', 1, 1),
    (p_org_id, v_attempt, v_store, v_loc_shelf, 'MAGGI-70G', 'duplicate_evidence', 'medium', 'Duplicate evidence flagged for review', 1, 5),
    (p_org_id, v_attempt, v_store, v_loc_back, 'MAGGI-70G', 'overdue_inspection', 'high', 'Backroom location not yet inspected', 0, 6);

  INSERT INTO public.expiry_future_actions (org_id, store_id, sku, action_type, due_at, metadata)
  VALUES (p_org_id, v_store, 'MAGGI-70G', 'next_inspection', now() + interval '7 days',
    '{"reason":"Follow-up after partial coverage"}'::jsonb);

  RETURN jsonb_build_object(
    'assignment_id', v_assignment,
    'attempt_id', v_attempt,
    'transfer_id', v_transfer,
    'message', 'Demo scenario seeded — development only'
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.seed_expiry_demo_scenario TO authenticated;
