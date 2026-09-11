-- P2: planogram facings columns, versioning metadata, multi-photo scans, execution workflow tables.

ALTER TABLE public.planogram_items
  ADD COLUMN IF NOT EXISTS expected_facings INT CHECK (expected_facings IS NULL OR expected_facings >= 0),
  ADD COLUMN IF NOT EXISTS min_facings INT CHECK (min_facings IS NULL OR min_facings >= 0),
  ADD COLUMN IF NOT EXISTS max_facings INT CHECK (max_facings IS NULL OR max_facings >= 0),
  ADD COLUMN IF NOT EXISTS expected_shelf_units INT CHECK (expected_shelf_units IS NULL OR expected_shelf_units >= 0);

COMMENT ON COLUMN public.planogram_items.expected_facings IS 'Visible front-facing count expected on shelf (KPI denominator for facing compliance)';
COMMENT ON COLUMN public.planogram_items.expected_shelf_units IS 'Optional inventory unit expectation — separate from visible facings';

ALTER TABLE public.planogram_versions
  ADD COLUMN IF NOT EXISTS effective_from TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS effective_to TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS store_format TEXT;

COMMENT ON COLUMN public.planogram_versions.store_format IS 'Optional store format label (hypermarket, kirana, dark store, etc.)';

ALTER TABLE public.shelf_scans
  ADD COLUMN IF NOT EXISTS photo_count INT NOT NULL DEFAULT 1 CHECK (photo_count >= 1),
  ADD COLUMN IF NOT EXISTS parent_scan_id UUID REFERENCES public.shelf_scans(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS shelf_scans_parent_scan_idx ON public.shelf_scans (parent_scan_id);

-- Commercial opportunities surfaced from scan analysis (persisted workflow beyond JSONB cache).
CREATE TABLE IF NOT EXISTS public.execution_opportunities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  scan_id UUID NOT NULL REFERENCES public.shelf_scans(id) ON DELETE CASCADE,
  store_id UUID REFERENCES public.stores(id) ON DELETE SET NULL,
  issue_type TEXT NOT NULL,
  brand TEXT,
  product_name TEXT,
  sku TEXT,
  severity TEXT NOT NULL DEFAULT 'medium',
  priority TEXT NOT NULL DEFAULT 'medium',
  expected_value TEXT,
  actual_value TEXT,
  gap_value TEXT,
  revenue_at_risk_inr NUMERIC(12, 2),
  commercial_impact_score NUMERIC(8, 2),
  confidence TEXT DEFAULT 'indicative',
  source TEXT DEFAULT 'scan_analysis',
  recommended_action TEXT,
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN (
      'open', 'assigned', 'in_progress', 'fixed',
      'rescan_required', 'verified', 'dismissed', 'closed'
    )),
  assigned_to UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS execution_opportunities_scan_idx
  ON public.execution_opportunities (scan_id, status);
CREATE INDEX IF NOT EXISTS execution_opportunities_org_idx
  ON public.execution_opportunities (org_id, status, priority);

CREATE TABLE IF NOT EXISTS public.execution_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  opportunity_id UUID NOT NULL REFERENCES public.execution_opportunities(id) ON DELETE CASCADE,
  scan_id UUID REFERENCES public.shelf_scans(id) ON DELETE SET NULL,
  action_type TEXT NOT NULL DEFAULT 'corrective'
    CHECK (action_type IN ('corrective', 'rescan', 'verify', 'assign', 'note')),
  actor_id UUID REFERENCES auth.users(id),
  notes TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS execution_actions_opportunity_idx
  ON public.execution_actions (opportunity_id, created_at DESC);

ALTER TABLE public.execution_opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.execution_actions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS execution_opportunities_select ON public.execution_opportunities;
CREATE POLICY execution_opportunities_select ON public.execution_opportunities
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS execution_opportunities_insert ON public.execution_opportunities;
CREATE POLICY execution_opportunities_insert ON public.execution_opportunities
  FOR INSERT TO authenticated
  WITH CHECK (public.is_org_member(org_id));

DROP POLICY IF EXISTS execution_opportunities_update ON public.execution_opportunities;
CREATE POLICY execution_opportunities_update ON public.execution_opportunities
  FOR UPDATE TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS execution_actions_select ON public.execution_actions;
CREATE POLICY execution_actions_select ON public.execution_actions
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS execution_actions_insert ON public.execution_actions;
CREATE POLICY execution_actions_insert ON public.execution_actions
  FOR INSERT TO authenticated
  WITH CHECK (public.is_org_member(org_id));
