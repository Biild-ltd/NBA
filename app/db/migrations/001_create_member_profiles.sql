-- Migration 001: Create member_profiles table
-- Run against your Supabase project via the SQL editor or CLI.

CREATE TABLE IF NOT EXISTS public.member_profiles (
  id               uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  full_name        text NOT NULL,
  enrollment_no    text NOT NULL UNIQUE,
  year_of_call     smallint NOT NULL CHECK (year_of_call >= 1900 AND year_of_call <= 2100),
  branch           text NOT NULL,
  phone_number     text NOT NULL,
  email_address    text NOT NULL,
  office_address   text NOT NULL,
  photo_url        text,
  qr_code_url      text,
  member_uid       text NOT NULL UNIQUE,   -- e.g. NBA-PM4H4H-MNLXRXM2
  profile_url      text NOT NULL,
  status           text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'active', 'suspended')),
  payment_ref      text,
  payment_status   text NOT NULL DEFAULT 'unpaid'
                     CHECK (payment_status IN ('unpaid', 'paid', 'refunded')),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_member_profiles_member_uid ON public.member_profiles(member_uid);
CREATE INDEX IF NOT EXISTS idx_member_profiles_status ON public.member_profiles(status);
CREATE INDEX IF NOT EXISTS idx_member_profiles_branch ON public.member_profiles(branch);
CREATE INDEX IF NOT EXISTS idx_member_profiles_payment_status ON public.member_profiles(payment_status);
CREATE INDEX IF NOT EXISTS idx_member_profiles_created_at ON public.member_profiles(created_at DESC);

-- Auto-update updated_at on any row modification
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS member_profiles_updated_at ON public.member_profiles;
CREATE TRIGGER member_profiles_updated_at
  BEFORE UPDATE ON public.member_profiles
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
