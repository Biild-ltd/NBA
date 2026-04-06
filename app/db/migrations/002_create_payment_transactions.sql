-- Migration 002: Create payment_transactions table

CREATE TABLE IF NOT EXISTS public.payment_transactions (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  member_id      uuid NOT NULL REFERENCES public.member_profiles(id) ON DELETE CASCADE,
  reference      text NOT NULL UNIQUE,    -- Paystack transaction reference
  amount         integer NOT NULL,        -- in kobo (e.g. 500000 = ₦5,000)
  currency       text NOT NULL DEFAULT 'NGN',
  status         text NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'success', 'failed')),
  paystack_data  jsonb,                   -- full webhook payload for audit
  created_at     timestamptz NOT NULL DEFAULT now(),
  verified_at    timestamptz
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_payment_transactions_member_id ON public.payment_transactions(member_id);
CREATE INDEX IF NOT EXISTS idx_payment_transactions_reference ON public.payment_transactions(reference);
CREATE INDEX IF NOT EXISTS idx_payment_transactions_status ON public.payment_transactions(status);
