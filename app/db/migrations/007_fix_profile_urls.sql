-- Fix profile_url values that were incorrectly set to the API domain
-- (api.nba.alphacards.dev) instead of the frontend domain (nba.alphacards.dev).
-- Safe to run multiple times (REPLACE is idempotent).

UPDATE public.member_profiles
SET profile_url = REPLACE(
        profile_url,
        'https://api.nba.alphacards.dev',
        'https://nba.alphacards.dev'
    )
WHERE profile_url LIKE 'https://api.nba.alphacards.dev%';
