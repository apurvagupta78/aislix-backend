-- Phase 3: territories hierarchy + manager verification on assignments
-- Uses existing RLS helpers: is_org_member(uuid), is_org_manager(uuid)

-- Ensure helpers exist (same signatures as 20260811120000_assigned_scans_planogram.sql)
CREATE OR REPLACE FUNCTION public.is_org_member(p_org_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.organization_members om
    WHERE om.org_id = p_org_id
      AND om.user_id = auth.uid()
      AND om.status = 'active'
  );
$$;

CREATE OR REPLACE FUNCTION public.is_org_manager(p_org_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.organization_members om
    WHERE om.org_id = p_org_id
      AND om.user_id = auth.uid()
      AND om.status = 'active'
      AND lower(om.role::text) IN ('owner', 'admin', 'manager', 'store_manager')
  );
$$;

CREATE OR REPLACE FUNCTION public.is_org_owner_or_admin(p_org_id UUID)
RETURNS BOOLEAN
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.organization_members om
    WHERE om.org_id = p_org_id
      AND om.user_id = auth.uid()
      AND om.status = 'active'
      AND lower(om.role::text) IN ('owner', 'admin')
  );
$$;

GRANT EXECUTE ON FUNCTION public.is_org_member(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_org_manager(UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_org_owner_or_admin(UUID) TO authenticated;

CREATE TABLE IF NOT EXISTS public.territories (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id uuid NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  name text NOT NULL,
  parent_id uuid REFERENCES public.territories(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS territories_org_id_idx ON public.territories(org_id);

ALTER TABLE public.stores
  ADD COLUMN IF NOT EXISTS territory_id uuid REFERENCES public.territories(id) ON DELETE SET NULL;

ALTER TABLE public.scan_assignments
  ADD COLUMN IF NOT EXISTS verified_at timestamptz,
  ADD COLUMN IF NOT EXISTS verified_by uuid REFERENCES auth.users(id) ON DELETE SET NULL;

ALTER TABLE public.territories ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS territories_select ON public.territories;
CREATE POLICY territories_select ON public.territories
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS territories_insert ON public.territories;
CREATE POLICY territories_insert ON public.territories
  FOR INSERT TO authenticated
  WITH CHECK (public.is_org_manager(org_id));

DROP POLICY IF EXISTS territories_update ON public.territories;
CREATE POLICY territories_update ON public.territories
  FOR UPDATE TO authenticated
  USING (public.is_org_manager(org_id))
  WITH CHECK (public.is_org_manager(org_id));

DROP POLICY IF EXISTS territories_delete ON public.territories;
CREATE POLICY territories_delete ON public.territories
  FOR DELETE TO authenticated
  USING (public.is_org_owner_or_admin(org_id));
