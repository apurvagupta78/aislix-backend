-- Ask Aislix request logging (no sensitive payloads).
CREATE TABLE IF NOT EXISTS public.ask_aislix_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  conversation_id UUID,
  question TEXT NOT NULL,
  tools_invoked TEXT[] NOT NULL DEFAULT '{}'::text[],
  status TEXT NOT NULL CHECK (status IN ('success', 'error', 'rate_limited')),
  latency_ms INT,
  token_usage JSONB,
  error_code TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ask_aislix_logs_org_idx ON public.ask_aislix_logs (org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ask_aislix_logs_user_idx ON public.ask_aislix_logs (user_id, created_at DESC);

ALTER TABLE public.ask_aislix_logs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ask_aislix_logs_select_own ON public.ask_aislix_logs;
CREATE POLICY ask_aislix_logs_select_own ON public.ask_aislix_logs
  FOR SELECT TO authenticated
  USING (user_id = auth.uid());

DROP POLICY IF EXISTS ask_aislix_logs_select_manager ON public.ask_aislix_logs;
CREATE POLICY ask_aislix_logs_select_manager ON public.ask_aislix_logs
  FOR SELECT TO authenticated
  USING (public.is_org_manager(org_id));

DROP POLICY IF EXISTS ask_aislix_logs_insert_own ON public.ask_aislix_logs;
CREATE POLICY ask_aislix_logs_insert_own ON public.ask_aislix_logs
  FOR INSERT TO authenticated
  WITH CHECK (user_id = auth.uid() AND public.is_org_member(org_id));
