# SETUP_AND_REMEDIATION.md — CampusResolve

A phased runbook to take this project from "never been run" to a verified,
Supabase- and Twilio-connected deployment — plus the list of known problems
found during review and how to fix each one.

Phases are ordered but 4 (Supabase) and 5 (Twilio) are independent of each
other. Each phase states a **Done when** check. Pick this up cold at any phase.

---

## Current state (as reviewed)

- Single git commit. No venv, no installed dependencies, no `.env`, no `db.sqlite3`.
- `DB_ENGINE` defaults to `sqlite`, so **no Supabase project has ever been contacted.**
- `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` blank, so attachments fall back to local `media/`.
- All three `TWILIO_*` blank, so `SMS_OTP_ENABLED` is `False` and SMS never appears.
- `BUILD_NOTES.md` admits the final code pass was written without network access,
  so `manage.py test` was never run against the shipped registration-OTP/Twilio
  code. The "49/49 passing" figure predates it and is **unverified**.

---

## Known problems and their fixes

| # | Problem | Where | Fix | Phase |
|---|---|---|---|---|
| 1 | `STATICFILES_DIRS` points at a `static/` directory that does not exist → `manage.py check` W004, and `CompressedManifestStaticFilesStorage` breaks `collectstatic` under `DEBUG=False` | `config/settings.py:120` | Create `static/.gitkeep` | 1 |
| 2 | Test suite never actually run against current code | `tests/` | Run it, record the real number | 2 |
| 3 | README claims "Login and complaint submission are rate-limited" — **not implemented** | `README.md:73` | Add `django-ratelimit`, decorate the views | 7 |
| 4 | HOD role and portal are undocumented — absent from roles, routes, data model and repo layout | `README.md`, `ARCHITECTURE.md`, `IMPLEMENTATION.md`, `CLAUDE.md` | Add HOD everywhere | 8 |
| 5 | OTP listed as a "Future enhancement" / "optional after MVP" — it is built and mandatory for students | `README.md:126`, `IMPLEMENTATION.md` Phase 13 | Move into the described flow | 8 |
| 6 | README implies Supabase Postgres is always used; the real default is SQLite via `DB_ENGINE` | `README.md:7` | Document the switch | 8 |
| 7 | Local setup section omits `create_director` / `create_hod` — following it leaves you with no Director account | `README.md:112-123` | Add both commands | 8 |
| 8 | Repo layout omits `hod_portal/`, `BUILD_NOTES.md`, `media/` | `README.md:78-98` | Update the tree | 8 |
| 9 | Unverified registrations are cleaned up only lazily, when someone re-registers the same email after the TTL | `apps/accounts/forms.py` | Add a periodic `manage.py` cleanup command | 9 |
| 10 | No CI config, no deployment platform config | — | Optional, out of MVP scope | 9 |

---

## Phase 0 — Environment and dependency pinning

The project targets Python 3.12+. The system Python here is **3.14**; not every
wheel (`scikit-learn`, `psycopg`) may exist for it yet. So: pin `requirements.txt`
to versions that have wheels for the interpreter you are on, then install.

```bash
cd CampusResolve
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
python -m pip install --upgrade pip
```

1. Edit `requirements.txt` and pin every entry to a concrete version
   (`Django==5.x.y`, `psycopg[binary]==3.x.y`, `django-environ==`,
   `scikit-learn==`, `supabase==`, `whitenoise==`, `gunicorn==`, `twilio==`).
   Add `django-ratelimit==` for Phase 7.
2. Install and lock:

```bash
pip install -r requirements.txt
pip check
pip freeze > requirements.lock.txt
```

**Fallback:** if a wheel fails to build on 3.14, install Python 3.12 and rebuild
the venv from it. Do not vendor-patch or drop `scikit-learn` — the TF-IDF path
in `apps/spam_detection/engine.py:167` needs it.

**Done when:** `pip check` is clean and
`python -c "import django, sklearn, supabase, twilio"` succeeds.

---

## Phase 1 — Local run on SQLite (baseline, no external services)

**Fix problem #1 first:**

```bash
mkdir static
# create an empty static/.gitkeep so the directory survives git
```

Then:

1. `cp .env.example .env` (Windows: `copy .env.example .env`)
2. Generate a real secret key and paste it into `DJANGO_SECRET_KEY`:
   ```bash
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```
3. Leave `DB_ENGINE=sqlite` and `DJANGO_DEBUG=True` for now.
4. Run the checks and bootstrap:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run   # confirms 0004 matches the models
python manage.py migrate
python manage.py seed_categories
python manage.py create_director --email director@yourcollege.edu --full-name "Jane Director" --password "changeme123"
python manage.py create_hod --email hod.cse@yourcollege.edu --full-name "Dr. Rao" --password "changeme123" --department CSE
python manage.py createsuperuser    # optional, for /admin/
python manage.py runserver
```

Valid `--department` values: `CSE`, `CST`, `ELECTRICAL`, `IT`, `MECHANICAL`.

**Done when:** `manage.py check` reports no issues (W004 gone) and
`http://127.0.0.1:8000/accounts/login/` renders.

---

## Phase 2 — Run the real test suite

This is the first genuine execution of `tests/test_registration_otp.py` and the
Twilio-mocked SMS tests.

```bash
python manage.py test tests -v 2
```

Triage map:

| Test file | Covers | A failure means |
|---|---|---|
| `test_authorization.py` | anonymous/student/director access matrix, forged POSTs | RBAC decorator or URL wiring broken |
| `test_complaint_workflow.py` | creation, status transitions, history, remark isolation | `apps/complaints/services.py` state machine |
| `test_hod_portal.py` | department scoping, identity withholding, cross-dept 403 | `apps/hod_portal/views.py` or `permissions.py` |
| `test_otp_login.py` | login OTP state machine | `apps/accounts/otp.py` |
| `test_registration_otp.py` | `is_active` gate, purpose scoping, SMS mocks, delivery-failure regression | `apps/accounts/otp.py` or `forms.py` |
| `test_spam_engine.py` | scoring bands, duplicate/burst/low-info | `apps/spam_detection/engine.py` |

**Done when:** the suite is green. Record the real test count here and correct
the unverified figures in `BUILD_NOTES.md` (problem #2).

> Actual result: _______ tests, _______ passing, on _______ (date)

---

## Phase 3 — Manual end-to-end walkthrough (SQLite)

Covers what the tests do not: the actual click path.

1. `/accounts/register/` → submit → account is created with `is_active=False`,
   nothing is logged in, and a 6-digit code is **printed to the runserver
   terminal** (console email backend). Copy it.
2. `/accounts/verify-registration/` → correct code → logged in.
   Also check: wrong code rejected; a 6th attempt locks even the correct code;
   an expired code (wait past `OTP_EXPIRY_MINUTES`) is rejected.
3. Log out, log back in → password accepted → a *new* code is emailed →
   `/accounts/verify-otp/` completes the login. Confirm you are not
   authenticated between those two steps.
4. Submit a complaint → open `/admin/` → confirm a `SpamAnalysis` row exists
   with component scores and human-readable reasons.
5. Register a second student → try to open the first student's complaint URL by
   its `complaint_code` → must be denied (the code is not authorization).
6. Log in as Director → **no OTP step** → dashboard → filter the list →
   change status → add a public remark **and** an internal note.
7. Log back in as the student → the public remark is visible, the internal
   note is **not** present anywhere in the page source.
8. As Director, forward the complaint to CSE → log in as the CSE HOD → the
   complaint appears, and the student's name, roll number and email appear
   **nowhere in the rendered HTML**. Change status and add an HOD remark.
9. Create an HOD for a different department → they get 403 on that same
   complaint URL, and 403 on any complaint never forwarded at all.
10. Upload an attachment as its owner, download it, then try the download URL
    while logged out and as a different student → denied.

**Done when:** all ten pass.

---

## Phase 4 — Supabase, from zero

### 4a. Account and project

1. Sign up at <https://supabase.com>, create an organization.
2. **New project.** Pick the region closest to your users (latency on every ORM
   query). Free tier is fine for the MVP.
3. **Save the database password it generates** — it is shown once. This becomes
   `DB_PASSWORD`.
4. Wait for provisioning to finish (~2 min).

### 4b. Connection string → `.env`

5. Project Settings → **Database** → Connection string.
   - Use the **direct connection / session pooler** (port 5432) for
     `manage.py migrate` and for a normal long-running Django server.
   - The transaction pooler (port 6543) is for serverless/short-lived
     connections and does not support all session-level features — do not
     point migrations at it.
   - If your network is IPv4-only, the direct host may not resolve; use the
     session pooler host instead.
6. Fill `.env` (these are read at `config/settings.py:80-91`):

```
DB_ENGINE=postgres
DB_NAME=postgres
DB_USER=postgres          # or postgres.<project-ref> for the pooler
DB_PASSWORD=<the password from step 3>
DB_HOST=<host from the connection string>
DB_PORT=5432
DB_SSLMODE=require
```

### 4c. Migrate onto Postgres

7. This is the first time the schema reaches Postgres:

```bash
python manage.py migrate
python manage.py seed_categories
python manage.py create_director --email director@yourcollege.edu --full-name "Jane Director" --password "<strong>"
python manage.py create_hod --email hod.cse@yourcollege.edu --full-name "Dr. Rao" --password "<strong>" --department CSE
```

8. Verify in the Supabase **Table Editor** that these exist:
   `accounts_user`, `accounts_loginotp`, `complaints_complaintcategory`,
   `complaints_complaint`, `complaints_attachment`,
   `complaints_complaintstatushistory`, `spam_detection_spamanalysis`,
   `audit_auditlog`.
9. Re-run the **whole of Phase 3** against Postgres. Same code, different
   backend — this is what proves the ORM-only claim.

### 4d. Storage bucket (private)

10. Storage → **New bucket** → name it exactly `complaint-attachments` →
    **Public toggle OFF**. The code assumes private + signed URLs
    (`apps/complaints/storage.py:71-84`); a public bucket silently defeats the
    entire attachment authorization model.
11. Project Settings → **API** → copy the Project URL and the **`service_role`**
    key.

    > ⚠️ `service_role` bypasses Row Level Security. It is a backend-only
    > credential. Never put it in a template, in JavaScript, in a client
    > bundle, or in a commit. If it ever leaks, rotate it immediately from
    > this same page.

12. Fill `.env`:

```
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service_role key>
SUPABASE_STORAGE_BUCKET=complaint-attachments
```

13. Restart the server, upload an attachment. Confirm in the Storage browser
    that the object landed at `complaints/<complaint-pk>/<uuid>.<ext>` —
    a UUID path, never the original filename
    (`apps/complaints/storage.py:36-43`).
14. Confirm the download goes through a **time-limited signed URL** (300s
    default), and that requesting the Django download route while logged out,
    or as a non-owner, is denied (`apps/complaints/views.py: attachment_download`).

### 4e. Why no RLS policies

15. None are needed for this design: Django connects as the database owner and
    is itself the authorization boundary (`ARCHITECTURE.md` §1). No
    browser-side Supabase client exists, so there is no untrusted party holding
    a Supabase key. **This must be revisited if a JS Supabase client is ever
    added** — at that point RLS becomes mandatory, not optional.

**Done when:** the full Phase 3 walkthrough passes against Supabase Postgres,
and an uploaded file is visible in the private bucket and reachable only
through Django.

---

## Phase 5 — Twilio, from zero

1. Sign up at <https://www.twilio.com/try-twilio> and verify your own phone.
2. **Understand the trial limits before testing:**
   - A trial account can only send SMS to numbers you have added under
     Phone Numbers → Manage → **Verified Caller IDs**. Add every test handset.
   - Trial messages carry a "Sent from your Twilio trial account" prefix.
3. Phone Numbers → **Buy a number** with the **SMS** capability (trial credit
   covers it). Note it in E.164 format, e.g. `+15551234567`.

   > 🇮🇳 **Indian destination numbers:** India requires DLT registration of the
   > sender ID and message templates. A trial US long code will likely **not**
   > deliver to Indian handsets. Test with a verified non-IN number first, and
   > budget for DLT registration before any real student use.

4. Console dashboard → copy **Account SID** and **Auth Token**.
5. Fill `.env`:

```
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=<auth token>
TWILIO_FROM_NUMBER=+15551234567
```

   `SMS_OTP_ENABLED` is **derived** from all three being non-empty
   (`config/settings.py:175`) — there is no separate on/off flag to forget.
6. Restart. The email/SMS radio buttons now appear on `/accounts/register/`
   and on both verify pages.
7. Register a student choosing **SMS** → the code arrives by text → verify →
   confirm `phone_verified=True` on that user row in `/admin/`.
8. **Failure-path check:** temporarily set a wrong `TWILIO_AUTH_TOKEN` and
   resend. You must get a readable on-screen error, **not** a 500 — every
   failure is funnelled through `OTPDeliveryError`
   (`apps/accounts/otp.py:137-146`). Restore the real token afterwards.
9. Check the mobile number format your registration form accepts
   (`apps/accounts/forms.py`). `_deliver_sms` passes `user.mobile_number`
   straight to Twilio, so stored values must be E.164 (`+91...`), not bare
   10-digit strings.

**Done when:** a real SMS OTP completes a registration and sets `phone_verified`.

---

## Phase 6 — Real email delivery (optional)

Replaces the console backend. In `.env`:

```
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=you@gmail.com
EMAIL_HOST_PASSWORD=<Gmail App Password, not your account password>
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=no-reply@yourcollege.edu
```

Gmail requires 2FA enabled and an **App Password** generated at
myaccount.google.com → Security → App passwords. Any SMTP provider works
(SendGrid, Mailgun, the college mail server).

**Failure-path check:** set a wrong password → readable on-screen error, not a
500. This is the regression documented in `BUILD_NOTES.md` §3
(`smtplib.SMTPAuthenticationError` subclasses `Exception`, not `OSError`).

---

## Phase 7 — Implement the missing rate limiting (problem #3)

`README.md:73` claims it; nothing implements it. The OTP model's own
attempt/resend caps protect the OTP step only — the initial email+password
check is currently unthrottled, as is complaint submission.

1. `pip install django-ratelimit` and add it (pinned) to `requirements.txt`.
2. Decorate in `apps/accounts/views.py`:
   - `EmailLoginView` POST — key on IP **and** on the submitted email.
   - `register` — key on IP.
   - `verify_otp_view`, `verify_registration` — key on IP.
3. Decorate in `apps/complaints/views.py`:
   - `complaint_create` — key on user.
4. Make the limits configurable from `.env`, matching the existing
   `SPAM_SUBMISSIONS_PER_HOUR` / `SPAM_SUBMISSIONS_PER_DAY` pattern.
5. Add `tests/test_rate_limiting.py` proving a throttled request is rejected.

Note this is application-level throttling; a reverse-proxy/WAF rule at the
infrastructure layer is still worth adding in production.

---

## Phase 8 — Fix the doc drift (problems #4–#8)

The four spec docs are pre-build and were never updated. Rewrite them to match
what actually shipped:

**`README.md`**
- Add the **HOD** role: department-scoped portal, Director→HOD forwarding,
  and the fact that student identity is never fetched into HOD context at all.
- Add HOD routes and `apps/hod_portal/` to the repository layout; also add
  `BUILD_NOTES.md`, `SETUP_AND_REMEDIATION.md` and `media/`.
- Document the `DB_ENGINE=sqlite|postgres` switch instead of implying Supabase
  Postgres is always in use (line 7).
- Move OTP out of "Future enhancements" (line 126) — it is shipped and
  mandatory for student login and registration.
- Keep the rate-limiting claim at line 73 — it becomes true after Phase 7.
- Add `create_director` and `create_hod` to Local setup (lines 112-123).

**`ARCHITECTURE.md`**
- §2: add HOD to the roles and describe the per-object
  `complaint.assigned_department == request.user.department` check.
- §3: add `assigned_department`, `assigned_at`, `assigned_by`, `hod_remark`.
- §8: add the HOD identity-withholding rule.
- §9: add `/hod/` and `/hod/complaints/<id>/`.

**`IMPLEMENTATION.md`**
- Add a Phase 16 for the HOD portal.
- Mark Phase 13 (OTP) as shipped and mandatory, not optional-after-MVP.

**`CLAUDE.md`**
- Add `HOD` to the roles list and `apps/hod_portal` to required apps.

**`BUILD_NOTES.md`**
- Replace the unverified "39/39" / "49/49 passing" claims with the real number
  recorded in Phase 2.

---

## Phase 9 — Production hardening

1. `.env`: `DJANGO_DEBUG=False`, a strong `DJANGO_SECRET_KEY`, strict
   `DJANGO_ALLOWED_HOSTS`, correct `CSRF_TRUSTED_ORIGINS`.
2. Behind HTTPS, set `SECURE_SSL_REDIRECT=True`, `SESSION_COOKIE_SECURE=True`,
   `CSRF_COOKIE_SECURE=True`. HSTS turns on automatically when `DEBUG=False`
   (`config/settings.py:198-201`).
3. `python manage.py collectstatic` — requires the Phase 1 `static/` fix.
4. `python manage.py check --deploy` must be clean.
5. Serve with `gunicorn config.wsgi:application`.
6. Confirm `.env` is gitignored and that no credential ever entered a commit
   (`git log -p -- .env` must return nothing).
7. **Problem #9:** add a `manage.py` command to purge expired unverified
   registrations, and schedule it. Today they are cleaned only lazily, when
   someone re-registers the same email after
   `REGISTRATION_UNVERIFIED_TTL_HOURS`.
8. **Problem #10:** add CI (run `check` + the test suite on push) and a
   deployment platform config. Neither exists.
9. Review the institutional data-retention and privacy policy before handling
   real grievances (`ARCHITECTURE.md` §11).

---

## Final verification checklist

- [ ] `manage.py check` clean
- [ ] `manage.py check --deploy` clean
- [ ] `manage.py test tests` green, count recorded
- [ ] Phase 3 walkthrough passes on SQLite
- [ ] Phase 3 walkthrough passes on Supabase Postgres
- [ ] Attachment lands in the private bucket, reachable only via a Django-authorized signed URL
- [ ] Real SMS OTP completes a registration, `phone_verified=True`
- [ ] Login throttle rejects after the limit, with a test proving it
- [ ] Every claim in `README.md` is traceable to shipped code
