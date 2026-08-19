# BUILD_NOTES.md — What was built

This is a working implementation of CampusResolve through the full 15-phase
plan in `IMPLEMENTATION.md`. `python manage.py check` and the full test
suite (28 tests) pass.

## Phase-by-phase status

| Phase | Status | Notes |
|---|---|---|
| 0 Bootstrap | Done | `config` project + 5 apps under `apps/` |
| 1 Supabase PostgreSQL | Done (see below) | Env-driven; `DB_ENGINE=sqlite\|postgres` |
| 2 Custom User | Done | Role-based, email login, self-promotion impossible |
| 3 Base UI/Auth | Done | Bootstrap 5 base template, login/logout, role-aware redirect |
| 4 Domain models | Done | All 7 models + `seed_categories` |
| 5 Student workflow | Done | Ownership-scoped dashboard/list/create/detail |
| 6 Rule-based spam engine | Done | Pure-Python `apps/spam_detection/engine.py`, unit tested |
| 7 Director authorization | Done | `director_required` decorator, independent per-route |
| 8 Director workflow | Done | Dashboard, filterable list, detail w/ status+remarks |
| 9 Supabase Storage | Done (dual-backend) | See below |
| 10 TF-IDF similarity | Done | scikit-learn, same-student-only comparison |
| 11 Analytics | Done | Chart.js, ORM aggregation, no PII in charts |
| 12 Confidential mode | Done | `is_confidential` flag + badge in Director views |
| 13 OTP | Done | Student login OTP + OTP-verified registration; email or SMS |
| 14 Tests | Done | `tests/` — auth matrix, workflow, spam engine |
| 15 Production hardening | Done | All toggles verified with `manage.py check --deploy` |

## Why SQLite locally, and how to switch to your real Supabase project

The sandbox this was built in cannot reach Supabase's network endpoints (its
egress is limited to package registries). So:

- `DB_ENGINE=sqlite` (the `.env` default) runs everything — migrations, the
  dev server, and all 28 tests — against local SQLite, using the exact same
  Django ORM code that runs against Postgres in production. No
  Supabase-specific SQL anywhere.
- To point at your real Supabase Postgres instance, edit `.env`:
  ```
  DB_ENGINE=postgres
  DB_NAME=postgres
  DB_USER=postgres
  DB_PASSWORD=<your password>
  DB_HOST=<your Supabase host>
  DB_PORT=5432
  DB_SSLMODE=require
  ```
  Then run `python manage.py migrate` from an environment that *can* reach
  Supabase (your laptop, CI, or the deployment host) — I was not able to run
  this migration myself in this session.

Same story for **Phase 9 attachments**: leave `SUPABASE_URL` /
`SUPABASE_SERVICE_ROLE_KEY` blank and uploads go to local `media/`
(`apps/complaints/storage.py`); fill them in and the exact same code path
uploads to your private `complaint-attachments` bucket via `supabase-py`,
with signed URLs generated server-side and never exposed to the client.

## How to run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # already done in this delivered copy
python manage.py migrate
python manage.py seed_categories
python manage.py create_director --email director@yourcollege.edu --full-name "Jane Director" --password "changeme123"
python manage.py createsuperuser   # optional, for /admin/
python manage.py runserver
```

Then visit `/accounts/register/` to create a student account, or
`/accounts/login/` with the director account above.

## Test suite

```bash
python manage.py test tests
```
28 tests covering: the full anonymous/student/director access matrix
(including forged POSTs and direct URL access), registration validation and
role-injection resistance, complaint creation, valid/invalid status
transitions, resolved-timestamp behavior, public-vs-internal remark
isolation, spam scoring (normal/low-info/repetitive/duplicate/burst cases),
and attachment size/type validation plus unauthorized-access denial.

## Added: HOD (Head of Department) portal

On top of the original 15-phase spec, this now adds a third role and portal:

- **New role**: `HOD`, with a `department` field on `User` (`CSE`, `CST`,
  `ELECTRICAL`, `IT`, `MECHANICAL`). Like Director, HOD accounts can only be
  created administratively — never via public registration (tested).
- **Director → HOD forwarding**: on any complaint's detail page, the
  Director can forward it to the HOD of a specific department
  (`apps/complaints/services.py: forward_complaint_to_department`). This
  records `assigned_department`, `assigned_at`, `assigned_by`, and an
  audit log entry — it does not change the complaint's status.
- **Student identity is withheld from HODs by design** — not just hidden in
  a template, but never fetched into the HOD-facing context at all
  (`apps/hod_portal/views.py: _complaint_summary`). HODs see the complaint
  code, category, subject, description, urgency, location, attachments, and
  status history — never the student's name, roll number, or email, even if
  `is_confidential=False`. This is intentional: it protects students from
  in-department retaliation regardless of whether they marked the complaint
  confidential.
- **New app** `apps/hod_portal/`, mirroring `director_portal`'s structure:
  a `hod_required` decorator enforces role AND a per-object check that
  `complaint.assigned_department == request.user.department` — an HOD for
  CSE gets 403 on a complaint forwarded to Mechanical, even via a guessed
  URL, and 403 on anything never forwarded at all.
- HODs can change status (same centralized `change_complaint_status`
  service Director uses, so the state machine and audit trail are identical)
  and write a `hod_remark`, which the student sees on their own complaint
  detail page alongside the Director's public remark.
- Provision an HOD account:
  ```bash
  python manage.py create_hod --email hod.cse@yourcollege.edu --full-name "Dr. Rao" --password "changeme123" --department CSE
  ```
  Valid `--department` values: `CSE`, `CST`, `ELECTRICAL`, `IT`, `MECHANICAL`.
- Logging in with an HOD account auto-redirects to `/hod/` instead of the
  student or Director dashboard.
- 11 new tests in `tests/test_hod_portal.py` cover: anonymous/student denial,
  department-scoped queue visibility, cross-department 403s, unforwarded-complaint
  403, identity never appearing in either HOD page's rendered HTML, status/remark
  updates, and role-injection resistance on registration. Full suite is now
  **39/39 passing**.

## Added: Student login OTP (Phase 13, adapted)

Your original spec's Phase 13 describes SMS OTP via a third-party provider
(Twilio, MSG91, etc.). I implemented it as **email-delivered OTP** instead,
for two concrete reasons: SMS needs a paid provider account and API keys I
don't have, and even with test keys, this sandbox's network can't reach
those providers anyway. Email needed zero new infrastructure — every
student already has one on file — and the delivery function is isolated
(`apps/accounts/otp.py: send_otp_email`) so swapping to real SMS later is a
one-function change, not a rewrite of the login flow.

- **Only Student logins get this step.** Director/HOD/Admin log in exactly
  as before — no OTP, no email sent.
- Flow: Student submits email+password → if correct, a 6-digit code is
  emailed and the session records a *pending* login (not yet authenticated)
  → student enters the code on `/accounts/verify-otp/` → only then is
  `django.contrib.auth.login()` actually called.
- Security properties: codes expire (`OTP_EXPIRY_MINUTES`, default 5),
  attempts are capped (`OTP_MAX_ATTEMPTS`, default 5 — exceeding it locks
  even the correct code, forcing a resend), resends are cooldown-limited
  (`OTP_RESEND_COOLDOWN_SECONDS`, default 30), and only a salted hash of the
  code is ever stored — the plaintext exists only in the outgoing email and
  is never written to any log or the audit trail.
- **Local dev needs zero setup**: `EMAIL_BACKEND` defaults to Django's
  console backend, so the "email" just prints to your `runserver` terminal
  — copy the 6-digit code from there.
- **For real delivery**, set in `.env`:
  ```
  EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
  EMAIL_HOST=smtp.gmail.com          # or your provider
  EMAIL_HOST_USER=you@gmail.com
  EMAIL_HOST_PASSWORD=<app password>  # not your normal password
  EMAIL_USE_TLS=True
  DEFAULT_FROM_EMAIL=no-reply@yourcollege.edu
  ```
- 9 new tests in `tests/test_otp_login.py`: pending (unauthenticated) state
  after password check, correct code completes login, wrong code rejected,
  codes are single-use, attempt-limit lockout, resend cooldown enforcement,
  hash-not-plaintext storage, Director bypasses OTP entirely, and the
  verify page is unreachable without a pending login. Full suite is now
  **49/49 passing**.

## Added: OTP-verified registration + SMS delivery channel

Two additions on top of the login OTP above.

### 1. Registration is now OTP-verified

A student account is no longer usable the moment the signup form is
submitted. The flow is:

1. `POST /accounts/register/` — the form validates and creates the User
   with **`is_active=False`**, then sends a verification code. Nothing is
   logged in. The user row and its first OTP are created inside a single
   `transaction.atomic()`, so if delivery fails the whole signup rolls
   back rather than leaving an unverifiable orphan account.
2. `POST /accounts/verify-registration/` — on the correct code the account
   is flipped to `is_active=True` (and `phone_verified=True` if the code
   came by SMS) and the student is logged straight in.

**Why `is_active` specifically:** Django's `ModelBackend.authenticate()`
calls `user_can_authenticate()` and returns `None` for inactive users. So
an unverified signup cannot log in *even if the password is correct*, and
that's enforced by Django's own auth machinery — not just by our view
logic. This is the real gate, which is what makes the feature more than a
frontend gesture.

Supporting details:

- `LoginOTP` gained **`purpose`** (`LOGIN` / `REGISTRATION`) and
  **`channel`** (`EMAIL` / `SMS`) — migration `0004_otp_purpose_channel.py`,
  which backfills existing rows to `LOGIN`/`EMAIL`. All lookups filter on
  purpose, so a registration code can never be replayed to satisfy a login
  check (there's a test for exactly that).
- Issuing a code now **supersedes** any outstanding code for the same
  user+purpose, so only the newest is ever live.
- Login errors stay deliberately generic. Telling an unverified user
  "account exists but isn't verified" would leak which emails are
  registered, so `/accounts/login/` shows the standard invalid-login
  message; recovery happens by re-registering, which re-sends a code.
- An abandoned unverified signup stops blocking its email/roll number
  after `REGISTRATION_UNVERIFIED_TTL_HOURS` (default 24), so a real
  student can't be locked out permanently by someone else's stale attempt.
- Registration passwords now run through Django's configured
  `AUTH_PASSWORD_VALIDATORS` via `validate_password()`, instead of only a
  `min_length=8` check.

### 2. SMS delivery (Twilio)

Same `LoginOTP` model, same verification path — only the transport
differs. Delivery lives behind `_deliver_email` / `_deliver_sms` in
`apps/accounts/otp.py`.

- Turns on automatically when all three `TWILIO_*` vars are set in `.env`
  (`SMS_OTP_ENABLED` is derived, so there's no separate flag to forget).
  Leave them blank and the SMS option simply never appears — email
  continues to work on its own.
- On the registration page, students pick email or SMS up front (radio
  buttons appear only when SMS is configured); on both verify pages they
  can switch channel when resending.
- Added `twilio>=9.0` to `requirements.txt`. The SMS tests mock Twilio
  entirely — they never make a real network call — and skip cleanly if the
  package isn't installed.

### 3. Delivery-failure handling (bug fix)

Every delivery failure, email or SMS, is now caught and re-raised as a
single `OTPDeliveryError` carrying a user-safe message. This fixes a real
bug: the previous code let `send_mail` exceptions propagate, and
`smtplib.SMTPAuthenticationError` subclasses `Exception` (not `OSError`),
so a wrong Gmail App Password produced an **unhandled 500** instead of a
readable error. `tests/test_registration_otp.py` has a regression test
that simulates exactly that.

### Verification status of this pass

Written and reviewed in a sandbox with **no network access to PyPI**, so
`pip install` and therefore `manage.py test` could not be run here. What
*was* checked: `python -m py_compile` on every `.py` file in
`apps/`, `config/` and `tests/`; a tag-balance check across all 16
templates; a standalone simulation of the OTP state machine (purpose
scoping, single-use, supersession, expiry, attempt cap); and confirmation
that the reworded email body still matches the existing tests' `code is:
(\d{6})` regex. Please run the real suite locally:

```bash
pip install -r requirements.txt
python manage.py makemigrations --check   # confirms 0004 matches the models
python manage.py migrate
python manage.py test tests
```

## Known gaps / deliberately deferred

- In-app rate-limiting on login/registration (infrastructure-level, e.g.
  `django-ratelimit` or reverse-proxy rule) is not implemented — the OTP
  system's own attempt/resend limits cover the OTP step specifically, but
  the initial email+password check has no throttle yet.
- Unverified accounts are cleaned up lazily (when someone re-registers the
  same email after the TTL). A periodic `manage.py` cleanup command would
  be tidier for a long-running deployment.
- No CI config was requested, so none was added.
- No deployment platform config has been added yet.
