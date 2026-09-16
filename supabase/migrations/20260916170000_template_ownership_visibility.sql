-- Personal / organization template ownership and visibility.
-- Private templates are visible only to owner_user_id unless shared.

ALTER TABLE public.audit_templates
  ADD COLUMN IF NOT EXISTS owner_user_id UUID REFERENCES auth.users(id),
  ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'organization'
    CHECK (visibility IN ('private', 'organization'));

-- Backfill ownership from created_by where available.
UPDATE public.audit_templates
SET owner_user_id = created_by
WHERE owner_user_id IS NULL AND created_by IS NOT NULL;

-- System templates are always organization-visible.
UPDATE public.audit_templates
SET visibility = 'organization'
WHERE is_system_template = true;

CREATE INDEX IF NOT EXISTS idx_audit_templates_org_visibility_owner
  ON public.audit_templates (org_id, visibility, owner_user_id);

-- Replace coarse org-wide policies with visibility-aware rules.
DROP POLICY IF EXISTS audit_templates_select ON public.audit_templates;
DROP POLICY IF EXISTS audit_templates_manage ON public.audit_templates;
DROP POLICY IF EXISTS audit_templates_insert ON public.audit_templates;
DROP POLICY IF EXISTS audit_templates_update ON public.audit_templates;
DROP POLICY IF EXISTS audit_templates_delete ON public.audit_templates;

CREATE POLICY audit_templates_select ON public.audit_templates
  FOR SELECT TO authenticated
  USING (
    public.is_org_member(org_id)
    AND (
      is_system_template = true
      OR visibility = 'organization'
      OR owner_user_id = auth.uid()
      OR created_by = auth.uid()
    )
  );

CREATE POLICY audit_templates_insert ON public.audit_templates
  FOR INSERT TO authenticated
  WITH CHECK (
    public.is_org_member(org_id)
    AND is_system_template = false
    AND owner_user_id = auth.uid()
    AND visibility IN ('private', 'organization')
  );

CREATE POLICY audit_templates_update ON public.audit_templates
  FOR UPDATE TO authenticated
  USING (
    public.is_org_member(org_id)
    AND is_system_template = false
    AND (
      owner_user_id = auth.uid()
      OR public.is_org_manager(org_id)
    )
  )
  WITH CHECK (
    public.is_org_member(org_id)
    AND is_system_template = false
    AND (
      owner_user_id = auth.uid()
      OR public.is_org_manager(org_id)
    )
  );

CREATE POLICY audit_templates_delete ON public.audit_templates
  FOR DELETE TO authenticated
  USING (
    public.is_org_member(org_id)
    AND is_system_template = false
    AND (
      owner_user_id = auth.uid()
      OR public.is_org_manager(org_id)
    )
  );

-- Managers may still seed system templates (bypasses owner check via service/manager path).
CREATE POLICY audit_templates_system_manage ON public.audit_templates
  FOR ALL TO authenticated
  USING (
    public.is_org_manager(org_id)
    AND is_system_template = true
  )
  WITH CHECK (
    public.is_org_manager(org_id)
    AND is_system_template = true
  );

-- Template versions follow parent template visibility.
DROP POLICY IF EXISTS audit_template_versions_select ON public.audit_template_versions;
DROP POLICY IF EXISTS audit_template_versions_manage ON public.audit_template_versions;

CREATE POLICY audit_template_versions_select ON public.audit_template_versions
  FOR SELECT TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.audit_templates t
      WHERE t.id = audit_template_versions.template_id
        AND t.org_id = audit_template_versions.org_id
        AND public.is_org_member(t.org_id)
        AND (
          t.is_system_template = true
          OR t.visibility = 'organization'
          OR t.owner_user_id = auth.uid()
          OR t.created_by = auth.uid()
        )
    )
  );

CREATE POLICY audit_template_versions_manage ON public.audit_template_versions
  FOR ALL TO authenticated
  USING (
    EXISTS (
      SELECT 1
      FROM public.audit_templates t
      WHERE t.id = audit_template_versions.template_id
        AND t.org_id = audit_template_versions.org_id
        AND public.is_org_member(t.org_id)
        AND (
          t.owner_user_id = auth.uid()
          OR public.is_org_manager(t.org_id)
        )
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1
      FROM public.audit_templates t
      WHERE t.id = audit_template_versions.template_id
        AND t.org_id = audit_template_versions.org_id
        AND public.is_org_member(t.org_id)
        AND (
          t.owner_user_id = auth.uid()
          OR public.is_org_manager(t.org_id)
        )
    )
  );

-- Owner can share a private template with the organization.
CREATE OR REPLACE FUNCTION public.share_audit_template_with_org(p_template_id UUID)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_org_id UUID;
  v_owner UUID;
  v_visibility TEXT;
BEGIN
  SELECT org_id, owner_user_id, visibility
  INTO v_org_id, v_owner, v_visibility
  FROM public.audit_templates
  WHERE id = p_template_id;

  IF v_org_id IS NULL THEN
    RAISE EXCEPTION 'Template not found';
  END IF;

  IF NOT public.is_org_member(v_org_id) THEN
    RAISE EXCEPTION 'Not authorized';
  END IF;

  IF v_owner IS DISTINCT FROM auth.uid() AND NOT public.is_org_manager(v_org_id) THEN
    RAISE EXCEPTION 'Only the template owner or a manager can share this template';
  END IF;

  IF v_visibility = 'organization' THEN
    RETURN;
  END IF;

  UPDATE public.audit_templates
  SET visibility = 'organization',
      updated_at = now(),
      updated_by = auth.uid()
  WHERE id = p_template_id;
END;
$$;

GRANT EXECUTE ON FUNCTION public.share_audit_template_with_org(UUID) TO authenticated;
