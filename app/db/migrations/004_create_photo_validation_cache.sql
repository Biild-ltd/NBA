-- Migration 004: Create photo_validation_cache table
-- Caches Claude Vision results keyed by image MD5 hash (24-hour TTL enforced in app).

CREATE TABLE IF NOT EXISTS public.photo_validation_cache (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  image_hash  text NOT NULL UNIQUE,   -- MD5 hex digest of image bytes
  result_json jsonb NOT NULL,         -- { "passed": bool, "score": float, "failures": [...] }
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Index for fast hash lookups and TTL pruning
CREATE INDEX IF NOT EXISTS idx_photo_cache_hash ON public.photo_validation_cache(image_hash);
CREATE INDEX IF NOT EXISTS idx_photo_cache_created ON public.photo_validation_cache(created_at);
