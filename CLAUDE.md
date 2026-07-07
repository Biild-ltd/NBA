# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

This repository currently contains only the PRD specification (`docs/NBA_Backend_PRD.md`). No application code exists yet. The PRD is the authoritative source of truth — read it before building anything.

## What to Build

The **Nigerian Bar Association (NBA) ID Card Portal** — a FastAPI backend for membership registration, AI-powered photo validation, payment processing, and digital ID card issuance.

**Spec file:** `docs/NBA_Backend_PRD.md`

## Stack

- **Python 3.12** · **FastAPI 0.111+**
- **Supabase** — Auth (JWT), PostgreSQL (RLS), Storage (S3-compatible)
- **Paystack** — payment gateway (Nigerian)
- **Claude Vision API** (`claude-opus-4-6` or `claude-sonnet-4-6`) — photo compliance validation
- **GCP Cloud Run** — deployment target (region: `africa-south1`)

## Commands

Once the project is initialised, these are the standard commands:

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload --port 8000

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_auth.py -v

# Run a single test
pytest tests/test_auth.py::test_register_success -v

# Build Docker image
docker build -t nba-backend .

# Run containerised locally
docker run --env-file .env -p 8080:8080 nba-backend
```

## Planned Project Structure

```
app/
├── main.py            # FastAPI app factory, middleware, router registration
├── config.py          # Pydantic settings — reads env vars + GCP Secret Manager
├── dependencies.py    # JWT verification, get_current_user, require_admin
├── routers/           # One file per domain: auth, profiles, photos, payments, qr, admin, utility
├── services/          # Business logic — one service per router domain
├── models/            # Pydantic request/response schemas
├── db/
│   ├── supabase.py    # Supabase client singleton
│   └── migrations/    # Sequential SQL files (001_...sql through 006_...sql)
└── constants/
    └── branches.py    # NBA branch enum
tests/                 # pytest — mirrors routers/ naming
Dockerfile
cloudbuild.yaml        # GCP Cloud Build CI/CD: test → build → push → deploy
.env.example
requirements.txt
```

## Architecture Patterns

**Layered flow:** `router → service → supabase client`. Routers handle HTTP concerns only; all business logic lives in services.

**Auth:** All protected routes verify Supabase JWTs via `dependencies.py`. Admin routes additionally check `user_metadata.role == "admin"` — this role is set server-side only, never via a user-facing endpoint.

**Database access:** Use the **service role key** (bypasses RLS) for all server-side operations. RLS policies exist as a defence-in-depth layer, not the primary access control mechanism for the API.

**Photo validation is two-stage:**
1. File-level checks (MIME from content, not extension; ≤5 MB; ≥200×200px; aspect ratio ≥3:4)
2. Claude Vision API checks 7 rules (white background, clear face, no sunglasses, not a selfie, passport framing, no heavy shadows, good lighting). Cache results by MD5 hash with 24-hour TTL in `photo_validation_cache` table. If Claude Vision is unavailable, fall back to Stage 1 only.

**Paystack webhooks:** Verify HMAC-SHA512 signature before processing. Always independently re-verify payment status via Paystack API. Handle duplicate webhooks idempotently.

**QR codes:** NBA green (`#1A5C2A`) on white, 400×400px PNG, error correction M (15%). Stored at `member-assets/qrcodes/{member_id}/qr.png` in Supabase Storage.

**member_uid format:** `NBA-XXXXXX-XXXXXXXX` (generated server-side, stored on profile).

## Required Environment Variables

```
SUPABASE_URL
SUPABASE_SERVICE_KEY      # bypasses RLS — never expose client-side
SUPABASE_ANON_KEY
SUPABASE_JWT_SECRET
PAYSTACK_SECRET_KEY
ANTHROPIC_API_KEY
MEMBERSHIP_FEE_KOBO       # fee is set server-side only
PUBLIC_BASE_URL
ENVIRONMENT               # development | production
```

In production, all secrets are sourced from **GCP Secret Manager** (not .env files).

## Implementation Order

Follow the phases in the PRD (section 13):
1. Core infrastructure + Supabase setup + FastAPI boilerplate + deployment pipeline
2. Auth & profiles
3. Photo validation pipeline
4. Paystack integration
5. QR code generation
6. Admin panel
7. Hardening (rate limiting via `slowapi`, monitoring, load testing)

## Key Constraints

- Minimum **80% test coverage** for services and routers.
- Photo validation target SLA: **< 5 seconds**.
- API p99 latency target: **< 3 seconds** (including photo validation paths).
- Cloud Run config: 2 vCPU, 1 GiB memory, 80 req/instance concurrency, 60s timeout, max 50 instances.
- MIME type validation must read file content — never trust the file extension.
