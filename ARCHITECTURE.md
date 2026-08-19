# ARCHITECTURE.md — CampusResolve

## 1. System boundary
```text
Student / Director Browser
          |
        HTTPS
          v
+-----------------------------+
| Django Application          |
| Auth + RBAC + CSRF          |
| Forms / validation          |
| Complaint services          |
| Spam scoring                |
| Director services           |
| Audit logging               |
+-----------+-----------------+
            | SQL/TLS                 server-side HTTPS
            v                              |
+----------------------+          +--------v---------+
| Supabase PostgreSQL  |          | Supabase Storage|
| source of truth      |          | private evidence|
+----------------------+          +------------------+
```
The browser is untrusted. Django is the authorization and business-logic boundary. Django ORM connects directly to Supabase PostgreSQL; a Supabase browser client is unnecessary for the MVP.

## 2. Authentication and RBAC
Use Django session authentication. Roles: STUDENT, DIRECTOR, ADMIN. Public registration always creates STUDENT. Director access must use a reusable server-side mixin/decorator and return 403 for unauthorized authenticated users.

Student object access must be ownership-scoped:
```python
get_object_or_404(Complaint, pk=pk, student=request.user)
```
Never fetch an arbitrary complaint and merely hide fields afterward.

## 3. Domain relationships
```text
User(STUDENT) 1 ---- * Complaint * ---- 1 ComplaintCategory
                         |
                         +---- * Attachment
                         +---- * ComplaintStatusHistory
                         +---- 0..1 SpamAnalysis

User(any actor) 1 ---- * AuditLog
```

## 4. Status state machine
Centralize transitions in a service:
```text
SUBMITTED -> UNDER_REVIEW | REJECTED | SPAM
UNDER_REVIEW -> IN_PROGRESS | REJECTED | SPAM
IN_PROGRESS -> RESOLVED | UNDER_REVIEW
RESOLVED -> CLOSED | IN_PROGRESS (optional reopen)
```
A status service validates transition, updates `resolved_at`, writes history and audit log inside `transaction.atomic()`.

## 5. Complaint creation flow
```text
Authenticated Student
 -> validated form
 -> server assigns request.user as owner
 -> create Complaint
 -> run spam analyzer
 -> save SpamAnalysis + summary score
 -> redirect to own complaint detail
```
Never accept `student`, `status`, `spam_score`, or role from student form input.

## 6. Spam engine
```text
Normalize text
  + exact same-user duplicate
  + recent submission frequency
  + low-information text
  + repetition patterns
  + confirmed spam history
  + TF-IDF similarity (phase 2)
        |
        v
weighted score + human-readable reasons
        |
NORMAL / REVIEW / SUSPICIOUS
```
The score does not delete or automatically suppress a grievance. Director performs final review. Cross-student similarity is treated cautiously because many students may legitimately report the same incident.

## 7. Storage
Use a private Supabase Storage bucket such as `complaint-attachments`. Store object metadata in PostgreSQL, not file bytes. Generate UUID object paths, validate size/type, and never trust original filenames. Access flow: request -> Django auth/ownership check -> short-lived authorized access/signed URL. Service-role credentials remain backend-only.

## 8. Confidentiality
`is_confidential=True` means verified-but-identity-restricted. Keep the student FK. Only explicitly authorized views expose identity. Internal Director notes are a separate field from public remarks.

## 9. Routes
Student:
```text
/accounts/register/
/accounts/login/
/dashboard/
/complaints/
/complaints/new/
/complaints/<public-id>/
```
Director:
```text
/director/
/director/complaints/
/director/complaints/<id>/
/director/spam-review/
/director/analytics/
```
Every Director route enforces Director permission independently.

## 10. Director dashboard
Cards: total, submitted, under review, in progress, resolved, suspected spam. Filters: complaint code, roll/name where policy allows, category, status, spam classification, date. Detail: complaint, permitted identity, evidence, spam reasons, history, public remark, internal note, status controls.

## 11. Data and privacy
Collect only required profile data. Avoid exposing phone/email in list pages. Do not put complaint text or PII into analytics logs. Define institutional retention/deletion policy before real deployment. Use HTTPS, secure cookies, strict allowed hosts, CSRF trusted origins, and environment-based secrets.

## 12. Useful indexes
- `(student, created_at)`
- `(status, created_at)`
- `(category, created_at)`
- `(spam_classification, created_at)`
- unique `complaint_code`
- unique `email`
- unique student `roll_number`

## 13. Deployment
```text
Browser -> HTTPS -> Django/Gunicorn -> Supabase PostgreSQL (SSL)
                              `-----> Supabase private Storage
```
Production: `DEBUG=False`, secure cookies, SSL redirect where appropriate, strict `ALLOWED_HOSTS`, no committed secrets, static-file strategy such as WhiteNoise/platform CDN.

## 14. Mandatory tests
Authentication, student ownership isolation, Director GET/POST denial for students, status transition/history, public-vs-internal remarks, duplicate/burst/normal spam cases, file validation, and unauthorized attachment retrieval.
