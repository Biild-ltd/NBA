-- Migration 006: Auth triggers
-- Automatically assigns the 'member' role to every new user on sign-up.
-- Admin role must be promoted manually via direct Postgres/Supabase Admin API.

CREATE OR REPLACE FUNCTION public.set_user_role()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE auth.users
  SET raw_app_meta_data = raw_app_meta_data || jsonb_build_object('role', 'member')
  WHERE id = NEW.id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.set_user_role();

-- ── Promoting a user to admin (run manually, never via API) ──────────────────
--
-- UPDATE auth.users
-- SET raw_app_meta_data = raw_app_meta_data || '{"role": "admin"}'
-- WHERE email = 'admin@nba.org.ng';
