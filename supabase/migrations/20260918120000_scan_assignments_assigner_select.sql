-- Allow assigners to read assignments they created (required for member/assigner Ask scope).
DROP POLICY IF EXISTS scan_assignments_assigner_select ON public.scan_assignments;
CREATE POLICY scan_assignments_assigner_select ON public.scan_assignments
  FOR SELECT TO authenticated
  USING (assigner_id = auth.uid());
