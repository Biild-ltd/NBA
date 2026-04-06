# Nigerian Bar Association — ID Card Portal
## Backend Service: Product Requirements Document

**Version:** 1.1  
**Status:** Draft — Ready for Development  
**Date:** April 2026  
**Stack:** Python 3.12 · FastAPI · Supabase (Auth + DB + Storage) · Paystack · GCP Cloud Run  
**Intended Consumer:** Claude Code / Engineering Team

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Goals & Non-Goals](#2-goals--non-goals)
3. [System Architecture Overview](#3-system-architecture-overview)
4. [Technology Stack](#4-technology-stack)
5. [Roles & Permissions](#5-roles--permissions)
6. [Data Model](#6-data-model)
7. [Feature Specifications](#7-feature-specifications)
   - 7.1 [Authentication & Authorisation](#71-authentication--authorisation)
   - 7.2 [Member Profile Management](#72-member-profile-management)
   - 7.3 [Passport Photograph Compliance Engine](#73-passport-photograph-compliance-engine)
   - 7.4 [Paystack Payment Integration](#74-paystack-payment-integration)
   - 7.5 [QR Code Generation](#75-qr-code-generation)
   - 7.6 [Admin Panel & Role-Based Access](#76-admin-panel--role-based-access)
8. [API Endpoint Reference](#8-api-endpoint-reference)
9. [Project Structure](#9-project-structure)
10. [GCP Deployment Strategy](#10-gcp-deployment-strategy)
11. [Security Requirements](#11-security-requirements)
12. [Non-Functional Requirements](#12-non-functional-requirements)
13. [Implementation Phases](#13-implementation-phases)
14. [Appendices](#14-appendices)

---

## 1. Executive Summary

This document specifies the complete backend system for the Nigerian Bar Association (NBA) ID Card Portal — a membership management platform that registers, verifies, and issues digital identity cards to Nigerian lawyers nationwide.

The system is designed to be cloud-native, scalable, secure, and production-ready from day one. It comprises six core capabilities:

- **Secure member registration and profile management** backed by Supabase Auth and PostgreSQL.
- **AI-powered passport photograph validation** that enforces compliance before any image is stored.
- **Integrated payment collection** via Paystack, enabling fee-gated card issuance.
- **Unique QR code generation** per member profile, supporting printable physical ID cards and instant digital verification.
- **Role-based admin panel** enabling administrators to view, search, manage, and act on all member registrations.
- **A GCP Cloud Run deployment architecture** capable of handling thousands of concurrent users with zero-downtime scaling.

---

## 2. Goals & Non-Goals

### 2.1 Goals

- Provide a RESTful FastAPI backend that serves the NBA ID Portal frontend.
- Authenticate users via Supabase Auth (email/password and magic link).
- Store and retrieve member profile data using Supabase PostgreSQL with Row Level Security (RLS).
- Validate uploaded passport photographs against strict visual compliance rules before persisting them to Supabase Storage.
- Accept membership fee payments through the Paystack payment gateway with full webhook verification.
- Generate a unique, scannable QR code for each approved member profile that links to their live public profile page.
- Provide a role-based admin interface allowing administrators to manage all members, view stats, search the directory, download QR codes, and export contact cards.
- Deploy on GCP in a manner that scales horizontally under load and remains cost-efficient at low traffic.

### 2.2 Non-Goals

- Frontend React/HTML implementation (already prototyped; this document covers backend only).
- Email notification templating beyond standard Supabase Auth emails (deferred to v2).
- Physical card printing logistics (out of scope for this backend).
- Third-party identity verification (NIN / BVN cross-check) is deferred to a future version.
- Real-time features (WebSockets, live updates) are not required for v1.

---

## 3. System Architecture Overview

The backend follows a layered architecture. All client requests are received by a FastAPI application running in GCP Cloud Run. Business logic is organised into routers, services, and repositories. Supabase acts as the managed backend-as-a-service layer providing JWT-based authentication, a PostgreSQL relational database, and an object storage bucket. Paystack handles all payment processing. Claude Vision API validates photograph compliance.

```
┌──────────────────────────────────────────────────────────────────┐
│                        CLIENT (Browser)                          │
│              HTML/React Frontend · Member & Admin UI             │
└────────────────────────────┬─────────────────────────────────────┘
                             │ HTTPS
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│              GCP Cloud Run — FastAPI Service                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │   Auth   │ │ Profiles │ │ Payments │ │  Admin   │  routers  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ PhotoSvc │ │  QRSvc   │ │ PaySvc   │ │ AdminSvc │  services │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
└──────┬──────────────┬───────────┬──────────────┬────────────────┘
       │              │           │              │
       ▼              ▼           ▼              ▼
┌────────────┐ ┌───────────┐ ┌────────┐ ┌─────────────┐
│  Supabase  │ │  Supabase │ │Paystack│ │Claude Vision│
│    Auth    │ │  DB + Sto │ │  API   │ │     API     │
└────────────┘ └───────────┘ └────────┘ └─────────────┘
```

### Component Interaction Summary

| From | To | Purpose |
|---|---|---|
| Frontend | FastAPI Cloud Run | All API calls over HTTPS |
| FastAPI | Supabase Auth | JWT verification, user creation |
| FastAPI | Supabase Database | Profile CRUD, payment records (RLS enforced) |
| FastAPI | Supabase Storage | Photo and QR code upload/download |
| FastAPI | Claude Vision API | Passport photo compliance validation |
| FastAPI | Paystack API | Transaction initialisation and verification |
| Paystack | FastAPI `/payments/webhook` | Payment confirmation (HMAC-signed) |
| FastAPI | qrcode library | QR PNG generation per member |

---

## 4. Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| API Framework | FastAPI 0.111+ | Async Python, auto OpenAPI docs, Pydantic v2 validation |
| Auth | Supabase Auth | JWT issuance, email/password + magic link, RLS integration |
| Database | Supabase PostgreSQL | Managed Postgres, RLS policies, instant REST APIs |
| File Storage | Supabase Storage | S3-compatible bucket for passport photos and QR PNGs |
| Payment | Paystack | Nigerian payment gateway, webhook-based confirmation |
| Photo Validation | Pillow + Claude Vision API | Rule-based + AI validation of passport photo compliance |
| QR Generation | `qrcode[pil]` library | Pure Python, generates PNG QR codes per member |
| Containerisation | Docker | Reproducible builds, local dev parity with Cloud Run |
| Deployment | GCP Cloud Run | Serverless containers, auto-scaling, pay-per-use |
| CI/CD | Cloud Build + Artifact Registry | Automated build, test, and deploy pipeline |
| Secrets | GCP Secret Manager | Secure storage of API keys and credentials |
| Observability | Cloud Logging + Monitoring | Centralised logs, uptime checks, alerting |

---

## 5. Roles & Permissions

The system supports two roles. Roles are enforced at both the FastAPI application layer (dependency injection) and the Supabase database layer (RLS policies).

### 5.1 Role Definitions

| Role | How Assigned | Description |
|---|---|---|
| `member` | Default on registration | Standard NBA member. Can manage own profile, view own payments, download own QR. |
| `admin` | Set manually by superadmin via Supabase custom claims | Full read access to all member records. Can manage member status, regenerate QR codes, export data. Cannot modify payment records directly. |

### 5.2 Role Assignment

Roles are stored as a **custom claim** in the Supabase JWT, set via a Postgres function triggered on the `auth.users` table:

```sql
-- Function to set role in JWT claims
CREATE OR REPLACE FUNCTION public.set_user_role()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE auth.users
  SET raw_app_meta_data = raw_app_meta_data || jsonb_build_object('role', 'member')
  WHERE id = NEW.id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger: assign 'member' role on every new signup
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.set_user_role();
```

Admin role is promoted manually:

```sql
UPDATE auth.users
SET raw_app_meta_data = raw_app_meta_data || '{"role": "admin"}'
WHERE email = 'admin@nba.org.ng';
```

### 5.3 Permission Matrix

| Endpoint Group | Member | Admin |
|---|---|---|
| `POST /auth/*` | ✅ | ✅ |
| `GET /profiles/me` | ✅ Own only | ✅ Any |
| `POST /profiles` | ✅ | ✅ |
| `PUT /profiles/me` | ✅ Own only | ✅ Any |
| `GET /profiles/{member_uid}` | ✅ Public | ✅ Public |
| `POST /photos/validate` | ✅ | ✅ |
| `POST /payments/initialise` | ✅ Own only | — |
| `GET /payments/history` | ✅ Own only | ✅ All |
| `POST /payments/webhook` | ❌ (Paystack only) | ❌ |
| `GET /qr/{member_uid}` | ✅ Own only | ✅ Any |
| `GET /admin/*` | ❌ | ✅ |
| `PATCH /admin/members/{id}/status` | ❌ | ✅ |
| `POST /admin/members/{id}/regenerate-qr` | ❌ | ✅ |
| `GET /admin/stats` | ❌ | ✅ |
| `GET /admin/export` | ❌ | ✅ |

### 5.4 FastAPI Role Enforcement

```python
# dependencies.py

from fastapi import Depends, HTTPException, status
from .auth import get_current_user

async def require_admin(current_user: dict = Depends(get_current_user)):
    role = current_user.get("app_metadata", {}).get("role")
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required."
        )
    return current_user
```

---

## 6. Data Model

### 6.1 Supabase Auth Integration

Supabase Auth manages the `auth.users` table automatically. Each registered user gets a UUID (`auth.users.id`). The application references this UUID as a foreign key in `public.member_profiles`. The application never stores passwords — Supabase Auth handles all credential management and JWT signing.

### 6.2 Table: `public.member_profiles`

```sql
CREATE TABLE public.member_profiles (
  id               uuid PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
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

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER member_profiles_updated_at
  BEFORE UPDATE ON public.member_profiles
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### 6.3 Table: `public.payment_transactions`

```sql
CREATE TABLE public.payment_transactions (
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
```

### 6.4 Row Level Security Policies

```sql
-- Enable RLS
ALTER TABLE public.member_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payment_transactions ENABLE ROW LEVEL SECURITY;

-- member_profiles: member can read/write only their own row
CREATE POLICY "member_self_select" ON public.member_profiles
  FOR SELECT USING (auth.uid() = id);

CREATE POLICY "member_self_insert" ON public.member_profiles
  FOR INSERT WITH CHECK (auth.uid() = id);

CREATE POLICY "member_self_update" ON public.member_profiles
  FOR UPDATE USING (auth.uid() = id);

-- member_profiles: public read for active profiles (QR scan)
CREATE POLICY "public_active_profile" ON public.member_profiles
  FOR SELECT USING (status = 'active');

-- payment_transactions: member sees own transactions only
CREATE POLICY "member_own_payments" ON public.payment_transactions
  FOR SELECT USING (
    member_id IN (
      SELECT id FROM public.member_profiles WHERE id = auth.uid()
    )
  );

-- Admin role bypasses RLS via service role key (backend only)
-- No explicit admin policy needed — service role key skips RLS entirely
```

> **Note:** Admin API endpoints use the **Supabase service role key** server-side, which bypasses RLS. This key is never exposed to the client.

### 6.5 Supabase Storage Bucket

| Property | Value |
|---|---|
| Bucket name | `member-assets` |
| Access | Private (URLs served via Supabase signed URLs or storage public policy) |
| Photo path | `photos/{member_id}/{uuid}.jpg` |
| QR code path | `qrcodes/{member_id}/qr.png` |
| Max file size | 5 MB (enforced at FastAPI layer before upload) |
| Allowed MIME | `image/jpeg`, `image/png` |

---

## 7. Feature Specifications

### 7.1 Authentication & Authorisation

The backend delegates all credential management to Supabase Auth. FastAPI verifies incoming JWT tokens on every protected route using the Supabase JWT secret.

#### 7.1.1 Registration Flow

1. Frontend calls `POST /auth/register` with `email` and `password`.
2. Backend calls Supabase Auth `createUser`; Supabase sends confirmation email.
3. The `on_auth_user_created` trigger fires, setting `role: member` in `app_metadata`.
4. User confirms email; Supabase issues JWT containing the `member` role claim.
5. Frontend stores the JWT and sends it as `Authorization: Bearer <token>` on all subsequent requests.

#### 7.1.2 JWT Verification Dependency

```python
# dependencies.py
from supabase import create_client
import jwt

async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False}
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token.")
```

---

### 7.2 Member Profile Management

Members submit their profile data via a `multipart/form-data` request containing all fields plus the passport photograph. The backend validates all inputs, runs the photo compliance pipeline, stores data, generates a `member_uid`, and responds with the complete member profile.

#### 7.2.1 Profile Fields

| Field | Type | Validation |
|---|---|---|
| `full_name` | string | Required. 2–150 chars. As it appears on call to bar certificate. |
| `enrollment_no` | string | Required. Unique. Pattern: alphanumeric + `/` (e.g. `SCN/12345`). |
| `year_of_call` | integer | Required. 4-digit year, 1900–current year. |
| `branch` | string | Required. Must be a value in the NBA branches enum list. |
| `phone_number` | string | Required. Valid Nigerian mobile number (starts `070|080|081|090|091`). |
| `email_address` | string | Required. Valid email format. |
| `office_address` | string | Required. 10–500 chars. Full chambers/office address. |
| `photo` | file | Required. JPG/PNG, max 5 MB. Must pass full compliance pipeline. |

#### 7.2.2 `member_uid` Generation

Each member receives a unique human-readable ID:

```python
import secrets, string

def generate_member_uid() -> str:
    chars = string.ascii_uppercase + string.digits
    part1 = ''.join(secrets.choice(chars) for _ in range(6))
    part2 = ''.join(secrets.choice(chars) for _ in range(8))
    return f"NBA-{part1}-{part2}"  # e.g. NBA-PM4H4H-MNLXRXM2
```

This UID is used in `profile_url` and encoded in the QR code.

#### 7.2.3 Profile URL Format

```
https://<PUBLIC_BASE_URL>/profile/<member_uid>
```

This URL is stable and never changes, even if the member updates their profile.

---

### 7.3 Passport Photograph Compliance Engine

Every uploaded photo must pass a **two-stage validation pipeline** before it is accepted and stored. If any stage fails, the upload is rejected with a structured error response.

#### 7.3.1 Stage 1 — File-Level Checks (Synchronous, <50ms)

Performed immediately in FastAPI before any AI call:

- MIME type must be `image/jpeg` or `image/png` — validated from **file content** using `python-magic`, not file extension.
- File size must not exceed **5 MB**.
- Image must be openable by Pillow with valid dimensions (minimum 200×200 px).
- Minimum portrait aspect ratio of **3:4** (height must be ≥ 1.33× width).

#### 7.3.2 Stage 2 — Visual Compliance Checks (Claude Vision API)

The image is sent to the Claude Vision API with a structured JSON prompt. The model evaluates the following rules and returns a structured assessment:

| Rule | Description |
|---|---|
| Plain background | White or light (near-white) background only. No colours, patterns, or busy scenes. |
| Face visible | Subject must face the camera directly. No profile or heavily angled shots. |
| No sunglasses | No tinted, mirrored, or dark eyewear. Clear prescription glasses are acceptable. |
| Not a selfie | No visible arms holding a phone. Camera must appear at or above eye level. |
| Passport framing | Head and upper shoulders only, centred in frame. No full-body shots. |
| No heavy shadows | Face must not have significant shadow coverage. |
| Good lighting | Face must be evenly and adequately lit. No extreme overexposure or underexposure. |

#### 7.3.3 Claude Vision Prompt

```python
PHOTO_VALIDATION_PROMPT = """
You are a passport photo compliance checker for a professional membership organisation.

Analyse this photograph and return ONLY a JSON object (no other text) with this exact structure:
{
  "passed": true | false,
  "score": 0.0 to 1.0,
  "failures": ["failure reason 1", "failure reason 2"]
}

Check these rules — fail on ANY violation:
1. Background must be plain white or very light (no colour, pattern, or busy background)
2. Face must be clearly visible and facing the camera directly
3. No sunglasses or tinted eyewear
4. Must not be a selfie (no visible arm, camera appears at or above eye level)
5. Passport-style framing: head and upper shoulders only, centred
6. No heavy shadows across the face
7. Good, even lighting — not severely over or underexposed

Set "passed" to true only if ALL rules pass. List each failed rule in "failures".
"""
```

#### 7.3.4 Validation Response Schema

```json
{
  "passed": true,
  "score": 0.94,
  "failures": []
}
```

```json
{
  "passed": false,
  "score": 0.42,
  "failures": [
    "Background is not plain white — a coloured wall is visible.",
    "Photo appears to be a selfie — arm is visible in frame."
  ]
}
```

If `passed` is `false`, the API returns **HTTP 422 Unprocessable Entity**. The photo is **never** written to storage.

#### 7.3.5 Fallback Behaviour

If the Claude Vision API is unavailable (timeout or network error), the system falls back to Stage 1 checks only and logs a `WARNING`. This ensures the service remains available even if the AI dependency is degraded.

#### 7.3.6 Photo Validation Caching

To avoid redundant AI calls, validation results are cached by image MD5 hash:

- Cache store: `public.photo_validation_cache` table in Supabase (columns: `image_hash`, `result_json`, `created_at`).
- TTL: 24 hours.
- Cache hit: Skip Stage 2 entirely, return cached result.

---

### 7.4 Paystack Payment Integration

Membership fee payment is required before a profile is activated and a QR code is issued.

#### 7.4.1 Payment Initialisation

1. Client calls `POST /payments/initialise`.
2. Backend reads the membership fee from server-side config (`MEMBERSHIP_FEE_KOBO`). **Amount is never accepted from the client.**
3. Backend calls Paystack's `POST /transaction/initialize` with the member's email, amount, and a unique `reference`.
4. Backend creates a `payment_transactions` record with `status=pending`.
5. Backend returns `{ authorization_url, reference }` to the client.
6. Client redirects user to `authorization_url` (Paystack hosted page).

#### 7.4.2 Payment Webhook Verification

1. Paystack sends `POST /payments/webhook` after payment.
2. Backend computes `HMAC-SHA512(raw_body, PAYSTACK_SECRET_KEY)` and compares against `x-paystack-signature` header. Requests failing this check → **HTTP 401**, logged.
3. If event is `charge.success`, backend independently calls `GET /transaction/verify/{reference}` on Paystack API to confirm.
4. On success, backend:
   - Updates `payment_transactions`: `status=success`, `verified_at=now()`, `paystack_data=<full payload>`.
   - Updates `member_profiles`: `payment_status=paid`, `status=active`, `payment_ref=<reference>`.
   - Triggers QR code generation asynchronously (see §7.5).
5. Returns HTTP 200 to Paystack within 30 seconds (Paystack requirement).

#### 7.4.3 Idempotency

The webhook handler checks whether the `reference` already exists in `payment_transactions` with `status=success`. Duplicate deliveries are **acknowledged silently** without re-processing.

#### 7.4.4 Payment Callback (Client-Side)

After the user completes payment on the Paystack page, they are redirected to a `callback_url`. The client calls `GET /payments/verify/{reference}` to poll for confirmation while the webhook processes asynchronously.

---

### 7.5 QR Code Generation

A unique QR code is generated for each member after successful payment. The QR code encodes the member's public profile URL.

#### 7.5.1 Generation Specification

| Property | Value |
|---|---|
| Library | `qrcode[pil]` |
| Content | `https://<PUBLIC_BASE_URL>/profile/<member_uid>` |
| Format | PNG, 400×400 px |
| Error correction | `ERROR_CORRECT_M` (15% recovery capacity) |
| Dark colour | `#1A5C2A` (NBA green) |
| Light colour | `#FFFFFF` |
| Storage path | `member-assets/qrcodes/{member_id}/qr.png` |
| Return value | Public URL stored in `member_profiles.qr_code_url` |

#### 7.5.2 Generation Code Sketch

```python
import qrcode
from qrcode.constants import ERROR_CORRECT_M
from PIL import Image
import io

def generate_qr_png(profile_url: str) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(profile_url)
    qr.make(fit=True)
    img = qr.make_image(
        fill_color="#1A5C2A",
        back_color="#FFFFFF"
    ).resize((400, 400), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

#### 7.5.3 Re-generation

Admins can trigger QR code re-generation via `POST /admin/members/{member_id}/regenerate-qr`. This overwrites the existing QR PNG in Supabase Storage and updates `member_profiles.qr_code_url`. The public profile URL (and QR content) remains stable across updates.

---

### 7.6 Admin Panel & Role-Based Access

The admin panel is accessible only to users with `role: admin` in their JWT claims. It provides a complete member directory with search, management actions, and statistics — as shown in the Admin UI screenshot.

#### 7.6.1 Admin Dashboard Stats

The `GET /admin/stats` endpoint returns:

```json
{
  "total_members": 1482,
  "active_members": 1301,
  "pending_members": 162,
  "suspended_members": 19,
  "paid_members": 1320,
  "unpaid_members": 162,
  "latest_member": {
    "full_name": "Chukwuemeka Obi",
    "created_at": "2026-04-05T14:22:00Z"
  },
  "members_by_branch": [
    { "branch": "Lagos", "count": 341 },
    { "branch": "Abuja", "count": 289 }
  ]
}
```

These stats map directly to the three summary cards in the Admin UI:
- **Total Members** → `total_members`
- **Synced to Sheets** → `active_members` (active = paid and approved)
- **Latest Member** → `latest_member.full_name`

#### 7.6.2 Member Directory (`GET /admin/members`)

Returns a paginated, searchable list of all members. Maps to the admin table showing: Photo · Full Name · Branch · Year · Enrolment · QR · Actions.

**Query Parameters:**

| Parameter | Type | Description |
|---|---|---|
| `q` | string | Free-text search across `full_name`, `branch`, `enrollment_no`, `year_of_call` |
| `status` | string | Filter by `pending \| active \| suspended` |
| `branch` | string | Filter by specific NBA branch |
| `year_of_call` | integer | Filter by year |
| `payment_status` | string | Filter by `unpaid \| paid` |
| `page` | integer | Page number (default: 1) |
| `page_size` | integer | Results per page (default: 50, max: 200) |
| `sort_by` | string | `created_at \| full_name \| branch` (default: `created_at`) |
| `sort_dir` | string | `asc \| desc` (default: `desc`) |

**Response:**

```json
{
  "total": 1482,
  "page": 1,
  "page_size": 50,
  "members": [
    {
      "id": "uuid",
      "member_uid": "NBA-PM4H4H-MNLXRXM2",
      "full_name": "Test Member",
      "branch": "Jos",
      "year_of_call": 2019,
      "enrollment_no": "12345",
      "status": "active",
      "payment_status": "paid",
      "photo_url": "https://...",
      "qr_code_url": "https://...",
      "profile_url": "https://.../profile/NBA-PM4H4H-MNLXRXM2",
      "created_at": "2026-04-05T14:22:00Z"
    }
  ]
}
```

#### 7.6.3 Admin Actions Per Member

The Actions column in the admin table exposes three per-member actions:

| Action | Button | Endpoint | Behaviour |
|---|---|---|---|
| View Profile | `Profile` | `GET /admin/members/{id}` | Returns full member detail including payment history |
| Download QR | `QR` | `GET /qr/{member_uid}/download` | Returns QR PNG as downloadable file attachment |
| Export Contact | `Contact` | `GET /admin/members/{id}/vcard` | Returns a `.vcf` vCard file for the member |

#### 7.6.4 Member Status Management

```
PATCH /admin/members/{member_id}/status
Body: { "status": "active" | "suspended" | "pending", "reason": "optional note" }
```

- Status transitions are logged to an `admin_audit_log` table (see §6.6).
- Suspending a member does not delete their profile or QR code.
- Reinstating a suspended member (`pending → active`) does not re-trigger payment if already paid.

#### 7.6.5 New Registration from Admin

Admins can initiate a new member registration via `POST /admin/members` with the same payload as the standard member registration flow, bypassing the payment requirement (for manually approved / waived members).

#### 7.6.6 Bulk Export

```
GET /admin/export?format=csv&status=active
```

Returns a CSV of all matching members with columns: `member_uid`, `full_name`, `branch`, `year_of_call`, `enrollment_no`, `email_address`, `phone_number`, `status`, `payment_status`, `created_at`.

### 6.6 Table: `public.admin_audit_log`

```sql
CREATE TABLE public.admin_audit_log (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  admin_id     uuid NOT NULL REFERENCES auth.users(id),
  action       text NOT NULL,           -- e.g. 'status_change', 'qr_regenerated'
  target_id    uuid NOT NULL,           -- member_profiles.id being acted on
  old_value    jsonb,
  new_value    jsonb,
  created_at   timestamptz NOT NULL DEFAULT now()
);
```

---

## 8. API Endpoint Reference

Base URL: `https://api.<domain>/v1`

### 8.1 Authentication

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/register` | None | Register new account with email + password |
| `POST` | `/auth/login` | None | Login; returns Supabase JWT access + refresh token |
| `POST` | `/auth/logout` | JWT | Invalidate current session |
| `POST` | `/auth/refresh` | None | Exchange refresh token for new access token |
| `POST` | `/auth/forgot-password` | None | Trigger Supabase password reset email |

### 8.2 Member Profiles

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/profiles/me` | JWT | Get authenticated user's full profile |
| `POST` | `/profiles` | JWT | Create new member profile (multipart/form-data + photo) |
| `PUT` | `/profiles/me` | JWT | Update own profile fields (re-runs photo validation if photo changed) |
| `GET` | `/profiles/{member_uid}` | None | Public profile lookup by member_uid (for QR scan) |

### 8.3 Photo Validation

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/photos/validate` | JWT | Validate photo only — returns pass/fail with reasons. Photo NOT stored. |
| `POST` | `/photos/upload` | JWT | Validate + store photo. Returns Supabase Storage URL on success. |

### 8.4 Payments

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/payments/initialise` | JWT | Initialise Paystack transaction. Returns `authorization_url`. |
| `GET` | `/payments/verify/{ref}` | JWT | Manually verify payment by reference (for client callback). |
| `POST` | `/payments/webhook` | None | Paystack webhook receiver. Verified via HMAC-SHA512. |
| `GET` | `/payments/history` | JWT | List authenticated user's payment transactions. |

### 8.5 QR Codes

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/qr/{member_uid}` | None | Return QR code PNG directly (for embedding/print templates). |
| `GET` | `/qr/{member_uid}/download` | JWT | Return QR PNG as a downloadable file attachment. |

### 8.6 Admin

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/admin/stats` | Admin JWT | Dashboard stats (totals, by branch, latest member). |
| `GET` | `/admin/members` | Admin JWT | Paginated, filterable member directory. |
| `POST` | `/admin/members` | Admin JWT | Create member registration (waives payment requirement). |
| `GET` | `/admin/members/{id}` | Admin JWT | Full member detail including payment history. |
| `PATCH` | `/admin/members/{id}/status` | Admin JWT | Update member status (active/suspended/pending). |
| `GET` | `/admin/members/{id}/vcard` | Admin JWT | Download member contact as `.vcf` vCard. |
| `POST` | `/admin/members/{id}/regenerate-qr` | Admin JWT | Regenerate QR code for a member. |
| `GET` | `/admin/export` | Admin JWT | Bulk CSV export of members. |
| `GET` | `/admin/audit-log` | Admin JWT | View admin action audit log. |

### 8.7 Utility

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/healthz` | None | Health check. Returns `{ "status": "ok" }`. |
| `GET` | `/branches` | None | List of all valid NBA branch names. |

---

## 9. Project Structure

```
nba-backend/
├── app/
│   ├── main.py                     # FastAPI app factory, CORS, middleware, router registration
│   ├── config.py                   # Pydantic BaseSettings — reads from env / Secret Manager
│   ├── dependencies.py             # Shared dependencies: get_current_user, require_admin, get_db
│   │
│   ├── routers/
│   │   ├── auth.py                 # POST /auth/*
│   │   ├── profiles.py             # GET|POST|PUT /profiles/*
│   │   ├── photos.py               # POST /photos/*
│   │   ├── payments.py             # POST|GET /payments/*
│   │   ├── qr.py                   # GET /qr/*
│   │   ├── admin.py                # GET|POST|PATCH /admin/*
│   │   └── utility.py              # GET /healthz, GET /branches
│   │
│   ├── services/
│   │   ├── auth_service.py         # Supabase Auth wrapper
│   │   ├── profile_service.py      # Profile CRUD business logic + member_uid generation
│   │   ├── photo_service.py        # Two-stage photo validation pipeline
│   │   ├── storage_service.py      # Supabase Storage upload/download/signed URL
│   │   ├── payment_service.py      # Paystack initialise + webhook verify + idempotency
│   │   ├── qr_service.py           # QR code PNG generation + upload
│   │   └── admin_service.py        # Member directory, stats, status management, audit logging
│   │
│   ├── models/
│   │   ├── profile.py              # Pydantic schemas: ProfileCreate, ProfileResponse, ProfileUpdate
│   │   ├── payment.py              # Pydantic schemas: PaymentInitResponse, WebhookPayload
│   │   ├── photo.py                # Pydantic schemas: PhotoValidationResult
│   │   └── admin.py                # Pydantic schemas: AdminMemberList, AdminStats, StatusUpdate
│   │
│   ├── db/
│   │   ├── supabase.py             # Supabase client singleton (anon + service role)
│   │   └── migrations/
│   │       ├── 001_create_member_profiles.sql
│   │       ├── 002_create_payment_transactions.sql
│   │       ├── 003_create_admin_audit_log.sql
│   │       ├── 004_create_photo_validation_cache.sql
│   │       ├── 005_rls_policies.sql
│   │       └── 006_auth_triggers.sql
│   │
│   └── constants/
│       └── branches.py             # List of all NBA branches (used for validation)
│
├── tests/
│   ├── conftest.py                 # pytest fixtures, test Supabase client
│   ├── test_auth.py
│   ├── test_profiles.py
│   ├── test_photo_validation.py
│   ├── test_payments.py
│   ├── test_qr.py
│   └── test_admin.py
│
├── Dockerfile
├── cloudbuild.yaml
├── .env.example
├── requirements.txt
└── README.md
```

---

## 10. GCP Deployment Strategy

The service is designed to support thousands of concurrent users. The architecture uses **GCP Cloud Run** — serverless containers with automatic horizontal scaling, no cluster management, and zero idle cost.

### 10.1 Core Infrastructure Components

| GCP Service | Role |
|---|---|
| **Cloud Run** | Hosts the FastAPI Docker container. Auto-scales from 1 to N instances based on request concurrency. |
| **Artifact Registry** | Stores versioned Docker images produced by Cloud Build. |
| **Cloud Build** | CI/CD pipeline triggered on Git push. Runs tests → builds image → pushes → deploys. |
| **Secret Manager** | Stores all sensitive credentials (Supabase keys, Paystack key, JWT secret, Anthropic key). |
| **Cloud Load Balancing** | Global HTTPS load balancer with Cloud Armor WAF for DDoS protection. |
| **Cloud CDN** | Caches public profile responses and static assets. |
| **Cloud Logging** | Centralised structured JSON logs from Cloud Run (stdout/stderr). |
| **Cloud Monitoring** | Uptime checks, p99 latency dashboards, error-rate alerting policies. |

### 10.2 Cloud Run Configuration

```yaml
# service.yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: nba-backend
  annotations:
    run.googleapis.com/ingress: all
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/minScale: "1"
        autoscaling.knative.dev/maxScale: "50"
        run.googleapis.com/cpu-throttling: "false"
    spec:
      containerConcurrency: 80
      timeoutSeconds: 60
      serviceAccountName: nba-backend-sa@<project>.iam.gserviceaccount.com
      containers:
        - image: <region>-docker.pkg.dev/<project>/nba/backend:latest
          resources:
            limits:
              cpu: "2"
              memory: 1Gi
          env:
            - name: ENVIRONMENT
              value: production
            - name: PUBLIC_BASE_URL
              value: https://nba.cards
          envFrom:
            - secretRef:
                name: nba-backend-secrets
```

| Parameter | Value | Rationale |
|---|---|---|
| Region | `africa-south1` (Johannesburg) | Closest GCP region to Nigerian users |
| Min instances | `1` | Prevents cold starts; always-on for the first request |
| Max instances | `50` | Handles thousands of concurrent users |
| Concurrency | `80` | FastAPI async; each instance handles many parallel requests |
| CPU | `2 vCPU` | Allocated during request — sufficient for photo validation |
| Memory | `1 GiB` | Sufficient for Pillow + qrcode image processing |
| Timeout | `60s` | Covers photo validation round-trip with Claude Vision |

### 10.3 Dockerfile

```dockerfile
FROM python:3.12-slim

# Install system dependencies for Pillow and python-magic
RUN apt-get update && apt-get install -y \
    libmagic1 \
    libjpeg-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE 8080

# Single worker — Cloud Run scales via instances, not workers
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
```

### 10.4 Cloud Build CI/CD Pipeline

```yaml
# cloudbuild.yaml
steps:
  # 1. Run tests
  - name: python:3.12-slim
    entrypoint: bash
    args:
      - -c
      - pip install -r requirements.txt && pytest tests/ -v --tb=short

  # 2. Build Docker image
  - name: gcr.io/cloud-builders/docker
    args:
      - build
      - -t
      - ${_REGION}-docker.pkg.dev/$PROJECT_ID/nba/backend:$SHORT_SHA
      - -t
      - ${_REGION}-docker.pkg.dev/$PROJECT_ID/nba/backend:latest
      - .

  # 3. Push image
  - name: gcr.io/cloud-builders/docker
    args:
      - push
      - --all-tags
      - ${_REGION}-docker.pkg.dev/$PROJECT_ID/nba/backend

  # 4. Deploy to Cloud Run
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    args:
      - gcloud
      - run
      - deploy
      - nba-backend
      - --image=${_REGION}-docker.pkg.dev/$PROJECT_ID/nba/backend:$SHORT_SHA
      - --region=${_REGION}
      - --platform=managed

  # 5. Smoke test
  - name: curlimages/curl
    args:
      - curl
      - --fail
      - https://nba-backend-<hash>-ew.a.run.app/healthz

substitutions:
  _REGION: africa-south1

options:
  logging: CLOUD_LOGGING_ONLY
```

### 10.5 Scaling Considerations for High Load

| Strategy | Detail |
|---|---|
| **Async FastAPI** | All I/O (Supabase, Paystack, Claude Vision) uses `async/await`. One instance handles 80+ concurrent requests without blocking. |
| **Stateless design** | No in-memory session state. All state in Supabase. Any instance handles any request. |
| **DB connection pooling** | Use Supabase's PgBouncer connection string (port `6543`, transaction mode) to avoid exhausting Postgres connections at scale. |
| **Photo validation caching** | Results cached by MD5 hash for 24 hours — avoids repeated Claude Vision calls for identical re-uploads. |
| **QR async generation** | QR codes generated in the payment webhook handler (async), not in the user-facing request path — keeps p99 latency low. |
| **Rate limiting** | `slowapi` middleware applies IP-based rate limiting on photo validation (5/min) and payment init (10/min) endpoints. |
| **Webhook idempotency** | Duplicate Paystack webhook deliveries detected and silently acknowledged. |
| **Min 1 instance** | Eliminates cold starts for regular business hours traffic. |

### 10.6 Environment Variables & Secrets

| Variable | Source | Description |
|---|---|---|
| `SUPABASE_URL` | Secret Manager | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Secret Manager | Service role key — bypasses RLS for admin ops |
| `SUPABASE_ANON_KEY` | Secret Manager | Anon key — for client-facing auth operations |
| `SUPABASE_JWT_SECRET` | Secret Manager | Used to verify Supabase-issued JWTs |
| `PAYSTACK_SECRET_KEY` | Secret Manager | Paystack secret key for API + webhook verification |
| `ANTHROPIC_API_KEY` | Secret Manager | Claude Vision API key for photo validation |
| `MEMBERSHIP_FEE_KOBO` | Env var | Membership fee in kobo (e.g. `500000` = ₦5,000) |
| `PUBLIC_BASE_URL` | Env var | Base URL for profile links in QR codes |
| `ENVIRONMENT` | Env var | `development` \| `staging` \| `production` |

---

## 11. Security Requirements

### 11.1 Authentication & Authorisation

- All non-public endpoints require a valid Supabase JWT in the `Authorization: Bearer` header.
- JWT signature is verified using the Supabase project JWT secret before any processing. Expired or tampered tokens → HTTP 401.
- Admin endpoints require `role: admin` in the JWT `app_metadata`. Missing or wrong role → HTTP 403.
- Row Level Security is enforced at the **database layer** as a second line of defence independent of application logic.

### 11.2 Payment Security

- Paystack webhook payloads are verified using `HMAC-SHA512`. Any request without a valid signature → HTTP 401, logged to Cloud Logging.
- The Paystack secret key is never exposed to the client. All server-side calls use the secret key only.
- Payment amounts are **never accepted from the client**. The backend reads the membership fee from server-side config only.
- Independent Paystack verification call (`GET /transaction/verify/{ref}`) is always made before updating member status, even after a valid webhook.

### 11.3 File Upload Security

- MIME type validated from file **content** using `python-magic`, not from the file extension.
- File size is checked before reading the full body into memory.
- Uploaded files are stored at paths containing random UUIDs, preventing enumeration.
- Supabase Storage bucket is **private**; only the service role key can write to it.

### 11.4 Admin Security

- Admin role is set server-side only via direct Postgres / Supabase Admin API — never via a user-facing endpoint.
- All admin actions (status changes, QR regeneration) are written to `admin_audit_log` with the admin's UUID, timestamp, and before/after values.
- Admin JWT claims are verified on every request — role escalation is not possible client-side.

### 11.5 Infrastructure Security

- All secrets stored in GCP Secret Manager — never in source code, environment variables directly, or version control.
- The Cloud Run service account has least-privilege IAM roles: `Secret Manager Secret Accessor`, `Artifact Registry Reader`, `Cloud Run Invoker` only.
- HTTPS is enforced end-to-end; Cloud Run provides automatic TLS.
- CORS is configured to allow only the production frontend origin(s) and the local dev origin.
- Request body size is limited globally in FastAPI (`app.add_middleware` with `ContentSizeLimitMiddleware`).

---

## 12. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Availability | 99.9% uptime (Cloud Run SLA). Min 1 instance prevents cold starts. |
| API Latency (p50) | < 200ms for profile read/write (excluding photo validation). |
| API Latency (p99) | < 3s including full two-stage photo validation. |
| Throughput | 500+ concurrent users per Cloud Run revision; thousands via auto-scaling. |
| Photo validation SLA | < 5s for the full pipeline under normal conditions. |
| Data durability | Supabase managed Postgres: point-in-time recovery + automated daily backups. |
| Test coverage | Minimum 80% line coverage for `services/` and `routers/` layers. |
| Observability | All requests logged as structured JSON to Cloud Logging with trace IDs. |
| Audit trail | All admin actions logged to `admin_audit_log` with full before/after state. |

---

## 13. Implementation Phases

| Phase | Scope | Key Deliverables |
|---|---|---|
| **Phase 1** | Core Infrastructure | Supabase project setup, FastAPI boilerplate, config, `get_current_user` dependency, Dockerfile, Cloud Run deployment, Cloud Build CI/CD, `/healthz`, `/branches`. |
| **Phase 2** | Auth & Profiles | `/auth/*` endpoints, DB migrations (member_profiles + RLS), profile CRUD, `member_uid` generation, Supabase Storage integration for photos. |
| **Phase 3** | Photo Validation | Two-stage validation pipeline (Pillow + Claude Vision), `/photos/validate` and `/photos/upload`, caching table, fallback handling. |
| **Phase 4** | Payments | Paystack initialise and webhook endpoints, `payment_transactions` table, webhook HMAC verification, idempotency, member status update on confirmation. |
| **Phase 5** | QR Codes | QR code generation service, async generation on payment webhook, `/qr/*` download and embed endpoints. |
| **Phase 6** | Admin Panel | `/admin/*` endpoints, `require_admin` dependency, member directory with search/filter/pagination, status management, bulk export, vCard, `admin_audit_log`. |
| **Phase 7** | Hardening | Rate limiting (`slowapi`), Cloud Monitoring dashboards + alerting, load testing (k6), security review, OWASP checklist. |

---

## 14. Appendices

### 14.1 Key External Documentation

- Paystack Accept Payments: https://paystack.com/docs/payments/accept-payments/
- Supabase Database: https://supabase.com/docs/guides/database/overview
- Supabase Auth: https://supabase.com/docs/guides/auth
- FastAPI: https://fastapi.tiangolo.com
- GCP Cloud Run: https://cloud.google.com/run/docs
- Anthropic API (Claude Vision): https://docs.anthropic.com/en/api/

### 14.2 NBA Branches Enum (Sample)

The `branch` field is validated against the official list of NBA branches. The list should be stored in `app/constants/branches.py` and sourced from the NBA secretariat. A representative sample:

```python
NBA_BRANCHES = [
    "Abuja", "Lagos", "Kano", "Ibadan", "Port Harcourt",
    "Enugu", "Kaduna", "Jos", "Benin City", "Onitsha",
    "Aba", "Abeokuta", "Ado-Ekiti", "Akure", "Asaba",
    "Awka", "Bauchi", "Calabar", "Ilorin", "Maiduguri",
    "Makurdi", "Nnewi", "Ondo", "Osogbo", "Owerri",
    "Sokoto", "Umuahia", "Uyo", "Warri", "Yola",
    # Full list to be sourced from NBA secretariat
]
```

### 14.3 Error Response Schema

All API errors follow a consistent JSON structure:

```json
{
  "error": {
    "code": "PHOTO_REJECTED",
    "message": "Your photo did not pass compliance checks.",
    "details": {
      "failures": [
        "Background is not plain white — a coloured wall is visible.",
        "Photo appears to be a selfie — arm is visible in frame."
      ],
      "score": 0.42
    }
  }
}
```

Standard error codes:

| Code | HTTP Status | Description |
|---|---|---|
| `INVALID_TOKEN` | 401 | JWT missing, expired, or invalid |
| `FORBIDDEN` | 403 | Authenticated but insufficient role |
| `PROFILE_NOT_FOUND` | 404 | No profile found for given member_uid |
| `DUPLICATE_ENROLLMENT` | 409 | Enrollment number already registered |
| `PHOTO_REJECTED` | 422 | Photo failed compliance validation |
| `PAYMENT_UNVERIFIED` | 402 | Action requires completed payment |
| `WEBHOOK_INVALID` | 401 | Paystack webhook signature mismatch |
| `VALIDATION_ERROR` | 422 | Pydantic input validation failed |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

### 14.4 Paystack Webhook Lifecycle

```
Paystack                          FastAPI Backend                    Supabase
   │                                    │                               │
   │  POST /payments/webhook             │                               │
   │  x-paystack-signature: <hmac>      │                               │
   ├───────────────────────────────────►│                               │
   │                                    │  Verify HMAC-SHA512           │
   │                                    │  ──────────────────           │
   │                                    │  ✅ Valid                      │
   │                                    │                               │
   │                                    │  GET /transaction/verify/{ref} │
   │◄───────────────────────────────────┤  (independent verification)   │
   ├───────────────────────────────────►│                               │
   │  { status: "success", ... }        │                               │
   │                                    │                               │
   │                                    │  UPDATE payment_transactions  │
   │                                    │  UPDATE member_profiles       │
   │                                    ├──────────────────────────────►│
   │                                    │                               │
   │                                    │  generate_qr_png()            │
   │                                    │  upload to Supabase Storage   │
   │                                    ├──────────────────────────────►│
   │                                    │                               │
   │  HTTP 200 OK                       │                               │
   │◄───────────────────────────────────┤                               │
   │  (within 30 seconds)              │                               │
```

### 14.5 `requirements.txt`

```
fastapi==0.111.0
uvicorn[standard]==0.29.0
pydantic[email]==2.7.1
pydantic-settings==2.2.1
supabase==2.4.4
python-jose[cryptography]==3.3.0
python-multipart==0.0.9
Pillow==10.3.0
python-magic==0.4.27
qrcode[pil]==7.4.2
httpx==0.27.0
anthropic==0.26.0
slowapi==0.1.9
pytest==8.2.0
pytest-asyncio==0.23.6
```

---

*Nigerian Bar Association ID Card Portal — Backend PRD v1.1 · Confidential*
