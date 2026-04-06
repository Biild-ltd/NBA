-- Migration 005: Row Level Security policies
-- Run AFTER migrations 001-004.

-- Enable RLS
ALTER TABLE public.member_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.photo_validation_cache ENABLE ROW LEVEL SECURITY;

-- ── member_profiles ──────────────────────────────────────────────────────────

-- Member can read only their own row
CREATE POLICY "member_self_select" ON public.member_profiles
  FOR SELECT USING (auth.uid() = id);

-- Member can create only their own row
CREATE POLICY "member_self_insert" ON public.member_profiles
  FOR INSERT WITH CHECK (auth.uid() = id);

-- Member can update only their own row
CREATE POLICY "member_self_update" ON public.member_profiles
  FOR UPDATE USING (auth.uid() = id);

-- Public (unauthenticated) read of active profiles — enables QR code scanning
CREATE POLICY "public_active_profile_select" ON public.member_profiles
  FOR SELECT USING (status = 'active');

-- ── payment_transactions ─────────────────────────────────────────────────────

-- Member sees only their own payment records
CREATE POLICY "member_own_payments_select" ON public.payment_transactions
  FOR SELECT USING (
    member_id IN (
      SELECT id FROM public.member_profiles WHERE id = auth.uid()
    )
  );

-- ── photo_validation_cache ───────────────────────────────────────────────────

-- Cache is read/written server-side only via service role key (bypasses RLS).
-- No user-facing RLS policy needed — deny all authenticated access.
-- Service role key operations are not restricted by RLS.

-- ── admin_audit_log ──────────────────────────────────────────────────────────
-- No user-facing RLS required — accessed exclusively via service role key.
ALTER TABLE public.admin_audit_log ENABLE ROW LEVEL SECURITY;
