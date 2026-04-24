-- Migration 003: Create admin_audit_log table

CREATE TABLE IF NOT EXISTS public.admin_audit_log (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  admin_id     uuid NOT NULL REFERENCES public.users(id),
  action       text NOT NULL,           -- e.g. 'status_change', 'qr_regenerated'
  target_id    uuid NOT NULL,           -- member_profiles.id being acted on
  old_value    jsonb,
  new_value    jsonb,
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_audit_log_admin_id ON public.admin_audit_log(admin_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_target_id ON public.admin_audit_log(target_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON public.admin_audit_log(created_at DESC);
