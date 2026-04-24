-- Migration 000: Auth tables
-- Run this FIRST, before all other migrations.
-- Replaces Supabase auth.users with our own users table.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Users ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.users (
  id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  email          text        NOT NULL UNIQUE,
  password_hash  text        NOT NULL,
  role           text        NOT NULL DEFAULT 'member'
                               CHECK (role IN ('member', 'admin')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON public.users(email);

CREATE OR REPLACE FUNCTION public.users_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS users_updated_at ON public.users;
CREATE TRIGGER users_updated_at
  BEFORE UPDATE ON public.users
  FOR EACH ROW EXECUTE FUNCTION public.users_updated_at();


-- ── Refresh tokens ────────────────────────────────────────────────────────────
-- One row per active session. Deleted on logout or when a new token is issued
-- (rotation). Cascades on user deletion.
CREATE TABLE IF NOT EXISTS public.refresh_tokens (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  token_hash  text        NOT NULL UNIQUE,   -- SHA-256 hex of the raw token
  expires_at  timestamptz NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id   ON public.refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash      ON public.refresh_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires   ON public.refresh_tokens(expires_at);


-- ── Password reset tokens ─────────────────────────────────────────────────────
-- Single-use tokens sent via email. used_at IS NULL means unused.
CREATE TABLE IF NOT EXISTS public.password_reset_tokens (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  token_hash  text        NOT NULL UNIQUE,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_prt_user_id  ON public.password_reset_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_prt_hash     ON public.password_reset_tokens(token_hash);
