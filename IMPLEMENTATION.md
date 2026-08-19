# IMPLEMENTATION.md — CampusResolve

Implement in this order. Keep each phase runnable and tested.

## Phase 0 — Bootstrap
Create venv, install requirements, start Django project `config`, and apps: `accounts`, `complaints`, `director_portal`, `spam_detection`, `audit`. Add `templates/`, `static/`, `tests/`. Commit `.env.example`, never `.env`.

Acceptance: `python manage.py check` passes.

## Phase 1 — Supabase PostgreSQL
Configure Django `DATABASES` entirely from environment variables:
```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME"),
        "USER": env("DB_USER"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST": env("DB_HOST"),
        "PORT": env("DB_PORT", default="5432"),
        "OPTIONS": {"sslmode": env("DB_SSLMODE", default="require")},
    }
}
```
Use the appropriate Supabase direct/pooler connection details for the deployment environment. Do not hard-code secrets.

Acceptance: migrations can connect and run.

## Phase 2 — Custom User
Before real migrations, implement custom `User` with role choices STUDENT/DIRECTOR/ADMIN and fields: unique email, student roll number, full name, mobile, course, branch, semester, phone_verified. Set `AUTH_USER_MODEL`.

Public registration always creates STUDENT; never expose role selection. Provision Director via admin/management command.

Acceptance: registration/login works; duplicate identity rejected; password is Django-hashed; self-promotion impossible.

## Phase 3 — Base UI/Auth
Implement Bootstrap base template, login/logout, messages, role-aware post-login redirects. Anonymous protected routes redirect to login. Keep CSRF enabled.

## Phase 4 — Domain models
Implement `ComplaintCategory`, `Complaint`, `Attachment`, `ComplaintStatusHistory`, `SpamAnalysis`, `AuditLog`. Add migrations and idempotent `seed_categories` command.

Complaint statuses: SUBMITTED, UNDER_REVIEW, IN_PROGRESS, RESOLVED, REJECTED, SPAM, CLOSED. Generate a unique human-readable code such as `CMP-2026-000123`; never use it as authorization.

## Phase 5 — Student workflow
Routes: dashboard, complaint list, create, detail. Form fields: category, subject, description, department/location, student urgency, confidential flag, optional attachment later.

Creation service must assign `request.user` server-side, create complaint, run spam analysis and save it in one coherent transaction. Student list/detail queries must be ownership-scoped.

Acceptance: Student A cannot view Student B's complaint even by changing URL IDs.

## Phase 6 — Rule-based spam engine
Implement a pure-Python testable service returning `final_score`, `classification`, component scores, and reasons.

Initial signals/possible weights:
- same-user exact/near duplicate: 30
- burst frequency: 25
- low-information text: 10
- excessive repetition: 15
- prior confirmed spam: 10
- other suspicious pattern: 10

Suggested business limits: 3 submissions/hour and 8/day, configurable in settings. Do not auto-delete or auto-mark status SPAM solely from the score.

Acceptance: normal text stays low; obvious duplicate/burst rises; flagged complaint remains stored.

## Phase 7 — Director authorization
Create `DirectorRequiredMixin`/decorator. Protect every `/director/` route. Students must receive 403 for Director GET and POST requests. Hiding nav items is only UI, never security.

## Phase 8 — Director workflow
Implement dashboard, complaint list/search/filter, detail, spam review. Add a centralized `change_complaint_status()` service using `transaction.atomic()` that validates allowed transitions, updates complaint/resolved timestamp, creates status history and audit log.

Separate `director_public_remark` from `director_internal_note`. Student views render only public remark.

## Phase 9 — Supabase Storage
Create private bucket `complaint-attachments`. Add backend-only Supabase credentials. Validate allowed formats (initially PDF/PNG/JPG), MIME/type and a configurable size cap (e.g. 5–10 MB). Generate UUID storage paths. Save metadata in `Attachment`.

Retrieval must pass through Django authorization before issuing authorized/signed access. Never expose service-role key in JS/templates.

## Phase 10 — TF-IDF similarity
After rule engine is stable, add scikit-learn TF-IDF + cosine similarity. Compare primarily against recent same-student complaints; optionally same category. Bound the component score. Do not punish multiple different students for reporting the same real incident.

## Phase 11 — Analytics
Director-only aggregate metrics: total/status counts, category distribution, complaints over time, suspected spam, average resolution time. Use Django ORM aggregation and Chart.js. Avoid PII in charts.

## Phase 12 — Confidential mode
`is_confidential=True` keeps verified student ownership but restricts identity display to authorized personnel. Label it confidential, not anonymous.

## Phase 13 — OTP (optional, after MVP)
Integrate an SMS provider only after core workflow is stable. OTPs require expiration, attempt limits, resend cooldown and safe storage; never log OTP values. Mark `phone_verified` only after successful verification.

## Phase 14 — Tests
At minimum test:
```text
anonymous -> protected student page: denied
anonymous -> director: denied
student -> own complaint: allowed
student -> another student's complaint: denied
student -> director GET: denied
student -> director POST: denied
director -> director dashboard: allowed
```
Also test registration validation, complaint creation, valid/invalid status transitions, history/resolved timestamp, public/internal note isolation, duplicate/burst/normal spam scoring, attachment size/type, unauthorized attachment access.

Run:
```bash
python manage.py check
python manage.py test
```

## Phase 15 — Production hardening
Use `DEBUG=False`, strict allowed hosts, HTTPS, secure session/CSRF cookies, CSRF trusted origins, environment secrets, PostgreSQL SSL, static-file strategy, structured error logging, backup/retention policy, and infrastructure request throttling. Review privacy policy before handling real grievances.

## MVP stop line
Do not expand scope until this works end-to-end:
`register -> login -> submit -> Supabase DB -> own tracking -> Director secure view -> status update -> student sees update -> history + spam analysis -> permission tests pass`.
