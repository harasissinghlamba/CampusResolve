# CLAUDE.md — CampusResolve Implementation Contract

You are implementing **CampusResolve**, a secure College Complaint & Grievance Management System. Read `README.md`, `ARCHITECTURE.md`, and `IMPLEMENTATION.md` before changing code. Treat them as the product and engineering specification.

## Non-negotiable stack
- Backend: Python + Django 5.x
- Web UI: Django Templates + Bootstrap 5 + vanilla JS
- Database: Supabase-hosted PostgreSQL, accessed through Django ORM
- Authentication: Django authentication/session framework for MVP
- Attachments: private Supabase Storage (production)
- Spam engine: Python rules first; TF-IDF/cosine similarity later
- Charts: Chart.js

Supabase Auth is **not** part of MVP. Never access PostgreSQL directly from browser code. Never expose DB credentials or Supabase service-role keys.

## Roles
`STUDENT`, `DIRECTOR`, `ADMIN`.

Public registration may create **STUDENT only**. Director accounts are provisioned administratively. `is_staff` alone is not Director authorization.

## Critical security rules
1. Enforce authorization server-side on every protected endpoint.
2. Students may view only complaints where `student=request.user`.
3. Every `/director/` route must reject non-Directors, including direct URL and forged POST requests.
4. Keep CSRF enabled; use Django password hashing and secure sessions.
5. Never trust user-supplied owner IDs, roles, status, filenames, MIME types, or complaint IDs.
6. Keep `.env` out of Git. Do not log passwords, OTPs, DB passwords, service keys, or attachment contents.
7. Private attachments require an ownership/role check before access.
8. Internal Director notes must never render in student responses.
9. Spam scoring must never automatically delete a complaint.
10. Add tests for authorization before considering a feature complete.

## Engineering rules
- Use a custom User model from the beginning (`AUTH_USER_MODEL`).
- Keep views thin; place status changes, spam scoring, and storage logic in services.
- Use `transaction.atomic()` for complaint+analysis creation and status+history updates.
- Use model/database constraints for uniqueness.
- Generate migrations for model changes.
- Prefer explicit, readable code over premature abstractions.
- Keep the app runnable after each implementation phase.
- Do not add React, DRF, Celery, Redis, Supabase Auth, OTP, or ML unless the current phase requires it.

## Required apps
`accounts`, `complaints`, `director_portal`, `spam_detection`, `audit`.

## Required core models
- User
- ComplaintCategory
- Complaint
- Attachment
- ComplaintStatusHistory
- SpamAnalysis
- AuditLog (recommended and expected for administrative actions)

## Complaint lifecycle
Primary: `SUBMITTED -> UNDER_REVIEW -> IN_PROGRESS -> RESOLVED -> CLOSED`.
Administrative outcomes: `REJECTED`, `SPAM`. Validate transitions in one service; do not scatter transition logic across views.

## Spam behavior
Return an explainable score and reasons. Suggested bands: 0–29 NORMAL, 30–59 REVIEW, 60–100 SUSPICIOUS. Signals: same-user duplicates, burst frequency, low-information text, excessive repetition, confirmed spam history, and later TF-IDF similarity. Similar reports from different students about a real campus incident must not automatically be treated as malicious.

## Implementation workflow
Follow `IMPLEMENTATION.md` in order. For each phase: inspect existing code, implement the smallest coherent slice, create migrations if needed, run `python manage.py check`, run relevant tests, fix failures, and summarize changed files plus any manual setup required.

## Definition of done
The MVP is done only when a student can register/login/submit/track a complaint; the record persists in Supabase PostgreSQL; a Director can securely view/update it; the student sees status/public remarks; status history is recorded; basic spam analysis is stored; cross-student and Director-route access controls have automated tests.
