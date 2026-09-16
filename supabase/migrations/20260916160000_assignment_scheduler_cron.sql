-- Server-side idempotent schedule runner + reminder processor + pg_cron hooks.

CREATE TABLE IF NOT EXISTS public.schedule_occurrences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  schedule_id UUID NOT NULL REFERENCES public.audit_schedules(id) ON DELETE CASCADE,
  occurrence_key TEXT NOT NULL,
  scheduled_for TIMESTAMPTZ NOT NULL,
  assignments_created INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (schedule_id, occurrence_key)
);

CREATE INDEX IF NOT EXISTS schedule_occurrences_schedule_idx
  ON public.schedule_occurrences (schedule_id, scheduled_for DESC);

ALTER TABLE public.schedule_occurrences ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS schedule_occurrences_select ON public.schedule_occurrences;
CREATE POLICY schedule_occurrences_select ON public.schedule_occurrences
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

DROP POLICY IF EXISTS schedule_occurrences_service ON public.schedule_occurrences;
CREATE POLICY schedule_occurrences_service ON public.schedule_occurrences
  FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE TABLE IF NOT EXISTS public.assignment_reminder_log (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  assignment_id UUID NOT NULL REFERENCES public.scan_assignments(id) ON DELETE CASCADE,
  reminder_type TEXT NOT NULL CHECK (reminder_type IN ('due_soon', 'overdue', 'escalation')),
  reminder_hours INT,
  sent_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (assignment_id, reminder_type, reminder_hours)
);

CREATE INDEX IF NOT EXISTS assignment_reminder_log_assignment_idx
  ON public.assignment_reminder_log (assignment_id);

ALTER TABLE public.assignment_reminder_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS assignment_reminder_log_service ON public.assignment_reminder_log;
CREATE POLICY assignment_reminder_log_service ON public.assignment_reminder_log
  FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Compute next run from cadence (server-side mirror of client recurrence).
CREATE OR REPLACE FUNCTION public.compute_schedule_next_run(
  p_cadence TEXT,
  p_day_of_week INT,
  p_day_of_month INT,
  p_from TIMESTAMPTZ DEFAULT now()
)
RETURNS TIMESTAMPTZ
LANGUAGE plpgsql
IMMUTABLE
AS $$
DECLARE
  v_next TIMESTAMPTZ := p_from;
BEGIN
  IF p_cadence = 'daily' THEN
    v_next := date_trunc('day', p_from) + INTERVAL '1 day' + INTERVAL '8 hours';
    IF v_next <= p_from THEN v_next := v_next + INTERVAL '1 day'; END IF;
    RETURN v_next;
  ELSIF p_cadence = 'weekly' THEN
    v_next := date_trunc('day', p_from) + ((COALESCE(p_day_of_week, 1) - EXTRACT(DOW FROM p_from)::INT + 7) % 7 + 1) * INTERVAL '1 day' + INTERVAL '8 hours';
    IF v_next <= p_from THEN v_next := v_next + INTERVAL '7 days'; END IF;
    RETURN v_next;
  ELSIF p_cadence = 'monthly' THEN
    v_next := date_trunc('month', p_from) + INTERVAL '1 month' + (LEAST(COALESCE(p_day_of_month, 1), 28) - 1) * INTERVAL '1 day' + INTERVAL '8 hours';
    IF v_next <= p_from THEN v_next := v_next + INTERVAL '1 month'; END IF;
    RETURN v_next;
  END IF;
  RETURN p_from + INTERVAL '7 days';
END;
$$;

-- Idempotent processor: creates assignments for due schedules exactly once per occurrence.
CREATE OR REPLACE FUNCTION public.process_due_audit_schedules(p_limit INT DEFAULT 100)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_schedule RECORD;
  v_occurrence_key TEXT;
  v_occurrence_id UUID;
  v_store_id UUID;
  v_assignee_id UUID;
  v_created INT := 0;
  v_schedules INT := 0;
  v_now TIMESTAMPTZ := now();
  v_due_at TIMESTAMPTZ;
  v_plan JSONB;
  v_entry JSONB;
  v_store_ids UUID[];
  v_assignee_ids UUID[];
  v_i INT;
BEGIN
  FOR v_schedule IN
    SELECT *
    FROM public.audit_schedules s
    WHERE (s.active = true OR s.status IN ('active', 'scheduled'))
      AND s.next_run_at IS NOT NULL
      AND s.next_run_at <= v_now
      AND (s.end_at IS NULL OR s.end_at > v_now)
      AND (s.max_occurrences IS NULL OR COALESCE(s.occurrence_count, 0) < s.max_occurrences)
    ORDER BY s.next_run_at ASC
    LIMIT p_limit
  LOOP
    v_occurrence_key := to_char(v_schedule.next_run_at AT TIME ZONE COALESCE(v_schedule.timezone, 'UTC'), 'YYYY-MM-DD"T"HH24:MI');

    INSERT INTO public.schedule_occurrences (org_id, schedule_id, occurrence_key, scheduled_for)
    VALUES (v_schedule.org_id, v_schedule.id, v_occurrence_key, v_schedule.next_run_at)
    ON CONFLICT (schedule_id, occurrence_key) DO NOTHING
    RETURNING id INTO v_occurrence_id;

    IF v_occurrence_id IS NULL THEN
      UPDATE public.audit_schedules
      SET next_run_at = public.compute_schedule_next_run(
            v_schedule.cadence, v_schedule.day_of_week, v_schedule.day_of_month, v_now + INTERVAL '1 minute'
          ),
          updated_at = v_now
      WHERE id = v_schedule.id;
      CONTINUE;
    END IF;

    v_due_at := v_schedule.next_run_at + INTERVAL '24 hours';
    IF v_schedule.due_config ? 'dueOffsetHours' THEN
      v_due_at := v_schedule.next_run_at + (COALESCE((v_schedule.due_config->>'dueOffsetHours')::INT, 24)) * INTERVAL '1 hour';
    END IF;

    v_plan := COALESCE(v_schedule.distribution_plan, '[]'::jsonb);

    IF jsonb_array_length(v_plan) > 0 THEN
      FOR v_entry IN SELECT * FROM jsonb_array_elements(v_plan)
      LOOP
        v_assignee_id := (v_entry->>'assigneeId')::UUID;
        FOR v_store_id IN
          SELECT jsonb_array_elements_text(v_entry->'storeIds')::UUID
        LOOP
          INSERT INTO public.scan_assignments (
            org_id, store_id, assignee_id, assigner_id, scope_type, scope_values,
            status, audit_mode, due_at, instructions, template_id, template_version,
            template_snapshot, evidence_policy, require_rca, reviewer_id,
            schedule_id, campaign_id, scheduled_at, assignment_state, creation_source
          ) VALUES (
            v_schedule.org_id,
            v_store_id,
            v_assignee_id,
            COALESCE(v_schedule.created_by, v_assignee_id),
            v_schedule.scope_type,
            COALESCE(v_schedule.scope_values, '{}'::jsonb),
            'pending',
            COALESCE(v_schedule.audit_mode, 'digital'),
            v_due_at,
            v_schedule.instructions,
            v_schedule.template_id,
            v_schedule.template_version,
            v_schedule.template_snapshot,
            v_schedule.evidence_policy,
            COALESCE(v_schedule.require_rca, true),
            v_schedule.reviewer_id,
            v_schedule.id,
            v_schedule.campaign_id,
            v_schedule.next_run_at,
            'assigned',
            'schedule'
          );
          v_created := v_created + 1;
        END LOOP;
      END LOOP;
    ELSE
      v_store_ids := CASE
        WHEN COALESCE(array_length(v_schedule.store_ids, 1), 0) > 0 THEN v_schedule.store_ids
        ELSE ARRAY[v_schedule.store_id]
      END;
      v_assignee_ids := CASE
        WHEN COALESCE(array_length(v_schedule.assignee_ids, 1), 0) > 0 THEN v_schedule.assignee_ids
        ELSE ARRAY[v_schedule.assignee_id]
      END;

      v_i := 0;
      FOREACH v_store_id IN ARRAY v_store_ids
      LOOP
        v_assignee_id := v_assignee_ids[1 + (v_i % array_length(v_assignee_ids, 1))];
        INSERT INTO public.scan_assignments (
          org_id, store_id, assignee_id, assigner_id, scope_type, scope_values,
          status, audit_mode, due_at, instructions, template_id, template_version,
          template_snapshot, evidence_policy, require_rca, reviewer_id,
          schedule_id, campaign_id, scheduled_at, assignment_state, creation_source
        ) VALUES (
          v_schedule.org_id,
          v_store_id,
          v_assignee_id,
          COALESCE(v_schedule.created_by, v_assignee_id),
          v_schedule.scope_type,
          COALESCE(v_schedule.scope_values, '{}'::jsonb),
          'pending',
          COALESCE(v_schedule.audit_mode, 'digital'),
          v_due_at,
          v_schedule.instructions,
          v_schedule.template_id,
          v_schedule.template_version,
          v_schedule.template_snapshot,
          v_schedule.evidence_policy,
          COALESCE(v_schedule.require_rca, true),
          v_schedule.reviewer_id,
          v_schedule.id,
          v_schedule.campaign_id,
          v_schedule.next_run_at,
          'assigned',
          'schedule'
        );
        v_created := v_created + 1;
        v_i := v_i + 1;
      END LOOP;
    END IF;

    UPDATE public.schedule_occurrences
    SET assignments_created = v_created
    WHERE id = v_occurrence_id;

    UPDATE public.audit_schedules
    SET
      last_run_at = v_now,
      occurrence_count = COALESCE(occurrence_count, 0) + 1,
      next_run_at = CASE
        WHEN v_schedule.assignment_mode = 'schedule_once' THEN NULL
        ELSE public.compute_schedule_next_run(
          v_schedule.cadence, v_schedule.day_of_week, v_schedule.day_of_month, v_now + INTERVAL '1 minute'
        )
      END,
      status = CASE
        WHEN v_schedule.assignment_mode = 'schedule_once' THEN 'completed'
        WHEN v_schedule.max_occurrences IS NOT NULL
          AND COALESCE(occurrence_count, 0) + 1 >= v_schedule.max_occurrences THEN 'completed'
        ELSE status
      END,
      active = CASE
        WHEN v_schedule.assignment_mode = 'schedule_once' THEN false
        WHEN v_schedule.max_occurrences IS NOT NULL
          AND COALESCE(occurrence_count, 0) + 1 >= v_schedule.max_occurrences THEN false
        ELSE active
      END,
      updated_at = v_now
    WHERE id = v_schedule.id;

    INSERT INTO public.notifications (user_id, org_id, type, title, body, payload)
    SELECT
      v_schedule.assignee_id,
      v_schedule.org_id,
      'scan_assigned',
      'Recurring audit generated',
      COALESCE(v_schedule.name, 'Scheduled audit') || ' — new assignments created.',
      jsonb_build_object('schedule_id', v_schedule.id, 'occurrence_key', v_occurrence_key);

    v_schedules := v_schedules + 1;
  END LOOP;

  RETURN jsonb_build_object('schedules_processed', v_schedules, 'assignments_created', v_created);
END;
$$;

GRANT EXECUTE ON FUNCTION public.process_due_audit_schedules(INT) TO service_role;
GRANT EXECUTE ON FUNCTION public.process_due_audit_schedules(INT) TO authenticated;

-- Due-soon and overdue reminders (idempotent via assignment_reminder_log).
CREATE OR REPLACE FUNCTION public.process_assignment_reminders(p_limit INT DEFAULT 500)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_row RECORD;
  v_hours INT;
  v_sent INT := 0;
  v_now TIMESTAMPTZ := now();
  v_escalation UUID;
BEGIN
  FOR v_row IN
    SELECT a.*,
      COALESCE(s.reminder_hours, '{24,12,4,1}'::INT[]) AS reminder_hours,
      s.escalation_user_id
    FROM public.scan_assignments a
    LEFT JOIN public.org_assignment_settings s ON s.org_id = a.org_id
    WHERE a.status IN ('pending', 'in_progress')
      AND a.due_at IS NOT NULL
      AND a.due_at > v_now - INTERVAL '7 days'
    ORDER BY a.due_at ASC
    LIMIT p_limit
  LOOP
    IF v_row.due_at < v_now THEN
      INSERT INTO public.assignment_reminder_log (assignment_id, reminder_type, reminder_hours)
      VALUES (v_row.id, 'overdue', NULL)
      ON CONFLICT DO NOTHING;
      IF FOUND THEN
        INSERT INTO public.notifications (user_id, org_id, type, title, body, payload)
        VALUES (
          v_row.assignee_id, v_row.org_id, 'scan_assigned',
          'Audit overdue',
          'An assigned audit is past its due date.',
          jsonb_build_object('assignment_id', v_row.id, 'reminder_type', 'overdue')
        );
        UPDATE public.scan_assignments SET assignment_state = 'overdue', updated_at = v_now
        WHERE id = v_row.id AND assignment_state NOT IN ('submitted', 'approved', 'cancelled');
        v_sent := v_sent + 1;

        IF v_row.escalation_user_id IS NOT NULL THEN
          INSERT INTO public.assignment_reminder_log (assignment_id, reminder_type, reminder_hours)
          VALUES (v_row.id, 'escalation', NULL)
          ON CONFLICT DO NOTHING;
          IF FOUND THEN
            INSERT INTO public.notifications (user_id, org_id, type, title, body, payload)
            VALUES (
              v_row.escalation_user_id, v_row.org_id, 'scan_assigned',
              'Overdue audit escalation',
              'An assigned audit is overdue and requires manager attention.',
              jsonb_build_object('assignment_id', v_row.id, 'reminder_type', 'escalation')
            );
            v_sent := v_sent + 1;
          END IF;
        END IF;
      END IF;
      CONTINUE;
    END IF;

    FOREACH v_hours IN ARRAY v_row.reminder_hours
    LOOP
      IF v_row.due_at <= v_now + (v_hours * INTERVAL '1 hour')
         AND v_row.due_at > v_now + ((v_hours - 1) * INTERVAL '1 hour') THEN
        INSERT INTO public.assignment_reminder_log (assignment_id, reminder_type, reminder_hours)
        VALUES (v_row.id, 'due_soon', v_hours)
        ON CONFLICT DO NOTHING;
        IF FOUND THEN
          INSERT INTO public.notifications (user_id, org_id, type, title, body, payload)
          VALUES (
            v_row.assignee_id, v_row.org_id, 'scan_assigned',
            format('Audit due in %s hours', v_hours),
            'Complete your assigned audit before the due date.',
            jsonb_build_object('assignment_id', v_row.id, 'reminder_hours', v_hours)
          );
          v_sent := v_sent + 1;
        END IF;
      END IF;
    END LOOP;
  END LOOP;

  RETURN jsonb_build_object('reminders_sent', v_sent);
END;
$$;

GRANT EXECUTE ON FUNCTION public.process_assignment_reminders(INT) TO service_role;

-- FMCG hierarchy: resolve outlet store IDs under a hierarchy node (includes descendants).
CREATE OR REPLACE FUNCTION public.resolve_hierarchy_outlet_stores(
  p_org_id UUID,
  p_profile_id UUID,
  p_node_id UUID
)
RETURNS TABLE (store_id UUID, node_id UUID, node_name TEXT, level_key TEXT, sales_rep_id UUID)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  WITH RECURSIVE subtree AS (
    SELECT n.id, n.parent_id, n.name, n.level_key, n.external_id, n.external_type, n.metadata
    FROM public.hierarchy_nodes n
    WHERE n.org_id = p_org_id AND n.profile_id = p_profile_id AND n.id = p_node_id AND n.active = true
    UNION ALL
    SELECT c.id, c.parent_id, c.name, c.level_key, c.external_id, c.external_type, c.metadata
    FROM public.hierarchy_nodes c
    INNER JOIN subtree p ON c.parent_id = p.id
    WHERE c.org_id = p_org_id AND c.active = true
  )
  SELECT
    COALESCE(
      CASE WHEN s.level_key = 'outlet' AND s.external_type = 'store' THEN s.external_id END,
      st.id
    ) AS store_id,
    s.id AS node_id,
    s.name AS node_name,
    s.level_key,
    (
      SELECT sr.external_id
      FROM subtree sr
      WHERE sr.level_key = 'sales_rep'
        AND sr.id IN (
          WITH RECURSIVE up AS (
            SELECT id, parent_id, level_key, external_id FROM subtree WHERE id = s.id
            UNION ALL
            SELECT n.id, n.parent_id, n.level_key, n.external_id
            FROM public.hierarchy_nodes n
            INNER JOIN up ON n.id = up.parent_id
          )
          SELECT id FROM up WHERE level_key = 'sales_rep' LIMIT 1
        )
      LIMIT 1
    ) AS sales_rep_id
  FROM subtree s
  LEFT JOIN public.stores st ON st.id = s.external_id AND s.external_type = 'store'
  WHERE s.level_key = 'outlet' OR (s.external_type = 'store' AND s.external_id IS NOT NULL);
$$;

GRANT EXECUTE ON FUNCTION public.resolve_hierarchy_outlet_stores(UUID, UUID, UUID) TO authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_hierarchy_outlet_stores(UUID, UUID, UUID) TO service_role;

-- Resolve assignees for sales reps linked to outlets.
CREATE OR REPLACE FUNCTION public.resolve_hierarchy_assignees(
  p_org_id UUID,
  p_profile_id UUID,
  p_node_id UUID,
  p_level_key TEXT DEFAULT NULL
)
RETURNS TABLE (user_id UUID, node_id UUID, node_name TEXT, level_key TEXT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  WITH RECURSIVE subtree AS (
    SELECT n.id, n.parent_id, n.name, n.level_key, n.external_id, n.external_type, n.metadata
    FROM public.hierarchy_nodes n
    WHERE n.org_id = p_org_id AND n.profile_id = p_profile_id AND n.id = p_node_id AND n.active = true
    UNION ALL
    SELECT c.id, c.parent_id, c.name, c.level_key, c.external_id, c.external_type, c.metadata
    FROM public.hierarchy_nodes c
    INNER JOIN subtree p ON c.parent_id = p.id
    WHERE c.org_id = p_org_id AND c.active = true
  )
  SELECT
    COALESCE(s.external_id, om.user_id) AS user_id,
    s.id AS node_id,
    s.name AS node_name,
    s.level_key
  FROM subtree s
  LEFT JOIN public.organization_members om
    ON om.org_id = p_org_id
    AND om.status = 'active'
    AND (
      lower(om.role::text) IN ('member', 'manager', 'admin', 'owner')
    )
    AND (
      s.metadata->>'employee_id' = om.user_id::TEXT
      OR s.metadata->>'user_id' = om.user_id::TEXT
      OR s.name ILIKE '%' || COALESCE(
        (SELECT p.full_name FROM public.profiles p WHERE p.id = om.user_id), ''
      ) || '%'
    )
  WHERE (p_level_key IS NULL OR s.level_key = p_level_key)
    AND (s.level_key IN ('sales_rep', 'employee') OR s.external_type = 'employee');
$$;

GRANT EXECUTE ON FUNCTION public.resolve_hierarchy_assignees(UUID, UUID, UUID, TEXT) TO authenticated;

-- Manual assignment grid: update assignment fields (manager only).
CREATE OR REPLACE FUNCTION public.update_assignment_grid_row(
  p_assignment_id UUID,
  p_assignee_id UUID DEFAULT NULL,
  p_due_at TIMESTAMPTZ DEFAULT NULL,
  p_assignment_state TEXT DEFAULT NULL,
  p_status TEXT DEFAULT NULL
)
RETURNS public.scan_assignments
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_row public.scan_assignments;
BEGIN
  SELECT * INTO v_row FROM public.scan_assignments WHERE id = p_assignment_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'Assignment not found'; END IF;
  IF NOT public.is_org_manager(v_row.org_id) THEN RAISE EXCEPTION 'Not authorized'; END IF;

  UPDATE public.scan_assignments
  SET
    assignee_id = COALESCE(p_assignee_id, assignee_id),
    due_at = COALESCE(p_due_at, due_at),
    assignment_state = COALESCE(p_assignment_state, assignment_state),
    status = COALESCE(p_status, status),
    updated_at = now()
  WHERE id = p_assignment_id
  RETURNING * INTO v_row;

  IF p_assignee_id IS NOT NULL THEN
    INSERT INTO public.notifications (user_id, org_id, type, title, body, payload)
    VALUES (
      p_assignee_id, v_row.org_id, 'scan_assigned',
      'Audit reassigned to you',
      'A manager updated your assignment.',
      jsonb_build_object('assignment_id', p_assignment_id)
    );
  END IF;

  RETURN v_row;
END;
$$;

GRANT EXECUTE ON FUNCTION public.update_assignment_grid_row(UUID, UUID, TIMESTAMPTZ, TEXT, TEXT) TO authenticated;

-- Register pg_cron jobs when extension is available (Supabase Pro / self-hosted).
-- Use $do$ / $cron$ tags so inner command strings do not terminate the DO block.
DO $do$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
    PERFORM cron.unschedule(jobid)
    FROM cron.job
    WHERE jobname IN ('aislix_process_due_schedules', 'aislix_process_assignment_reminders');

    PERFORM cron.schedule(
      'aislix_process_due_schedules',
      '*/5 * * * *',
      $cron$SELECT public.process_due_audit_schedules(200);$cron$
    );

    PERFORM cron.schedule(
      'aislix_process_assignment_reminders',
      '*/15 * * * *',
      $cron$SELECT public.process_assignment_reminders(500);$cron$
    );
  END IF;
EXCEPTION
  WHEN undefined_table OR undefined_function THEN
    RAISE NOTICE 'pg_cron not available — call process_due_audit_schedules() via Supabase scheduled Edge Function or external cron.';
END;
$do$;
