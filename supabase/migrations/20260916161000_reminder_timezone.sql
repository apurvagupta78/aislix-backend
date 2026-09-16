-- Reminder processor: include schedule/org timezone in notification payload.

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
  v_tz TEXT;
BEGIN
  FOR v_row IN
    SELECT a.*,
      COALESCE(s.reminder_hours, '{24,12,4,1}'::INT[]) AS reminder_hours,
      s.escalation_user_id,
      COALESCE(sch.timezone, 'Asia/Kolkata') AS location_timezone
    FROM public.scan_assignments a
    LEFT JOIN public.org_assignment_settings s ON s.org_id = a.org_id
    LEFT JOIN public.audit_schedules sch ON sch.id = a.schedule_id
    WHERE a.status IN ('pending', 'in_progress')
      AND a.due_at IS NOT NULL
      AND a.due_at > v_now - INTERVAL '7 days'
    ORDER BY a.due_at ASC
    LIMIT p_limit
  LOOP
    v_tz := COALESCE(v_row.location_timezone, 'Asia/Kolkata');

    IF v_row.due_at < v_now THEN
      INSERT INTO public.assignment_reminder_log (assignment_id, reminder_type, reminder_hours)
      VALUES (v_row.id, 'overdue', NULL)
      ON CONFLICT DO NOTHING;
      IF FOUND THEN
        INSERT INTO public.notifications (user_id, org_id, type, title, body, payload)
        VALUES (
          v_row.assignee_id, v_row.org_id, 'scan_assigned',
          'Audit overdue',
          format('An assigned audit is past its due date (timezone: %s).', v_tz),
          jsonb_build_object('assignment_id', v_row.id, 'reminder_type', 'overdue', 'timezone', v_tz)
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
              format('An assigned audit is overdue (timezone: %s).', v_tz),
              jsonb_build_object('assignment_id', v_row.id, 'reminder_type', 'escalation', 'timezone', v_tz)
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
            format(
              'Complete your assigned audit before the due date (%s local schedule timezone).',
              v_tz
            ),
            jsonb_build_object(
              'assignment_id', v_row.id,
              'reminder_hours', v_hours,
              'timezone', v_tz,
              'due_at', v_row.due_at
            )
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
