# CampusResolve — College Complaint & Grievance Management System

CampusResolve is a secure grievance portal for colleges. Verified students submit and track complaints; the Director receives a protected dashboard to review, triage, update and resolve them. The application also calculates an explainable spam-risk score to help identify duplicate or mischievous submissions without silently discarding genuine grievances.

## Stack
- **Backend:** Django 5.x / Python 3.12+
- **Database:** Supabase-hosted PostgreSQL via Django ORM
- **Authentication:** Django Auth + sessions
- **Frontend:** Django Templates, Bootstrap 5, vanilla JavaScript
- **Attachments:** private Supabase Storage
- **Spam detection:** Python rules; later scikit-learn TF-IDF + cosine similarity
- **Analytics:** Chart.js

> Supabase provides managed PostgreSQL; Django remains the application backend and authorization boundary.

## Users and permissions
### Student
Registers with name, university roll number, college email, mobile number, course, branch, semester and password. Can submit complaints, upload evidence, see only their own complaints, status history and public Director remarks.

### Director
Can access the protected Director portal, view all complaints and permitted student identity, search/filter, review spam signals, change status, add public remarks/internal notes, resolve/reject/mark spam, and view analytics.

### Admin
Technical administration. A Django superuser is not automatically the normal Director workflow.

## Complaint categories
Academic, Examination, Fees, Infrastructure, Hostel, Library, Transport, Canteen, Faculty/Staff, Harassment/Safety, IT/Portal, Other. Store categories in `ComplaintCategory` so they can be enabled/disabled without code changes.

## Complaint lifecycle
`SUBMITTED -> UNDER_REVIEW -> IN_PROGRESS -> RESOLVED -> CLOSED`

Administrative outcomes: `REJECTED`, `SPAM`. Every status change creates `ComplaintStatusHistory`.

## Spam detection
Spam detection is decision support, not automatic deletion. Suggested score:
- 0–29 NORMAL
- 30–59 REVIEW
- 60–100 SUSPICIOUS

Signals include exact/near duplicates from the same student, unusual submission frequency, extremely low-information text, excessive repeated characters/words, prior confirmed spam, and later TF-IDF/cosine similarity. Profanity alone is not spam. Similar complaints from different students may indicate a real common problem.

## Core data model
### User
`email`, `roll_number`, `full_name`, `mobile_number`, `course`, `branch`, `semester`, `role`, `phone_verified`, plus Django auth fields.

### ComplaintCategory
`name`, `slug`, `is_active`.

### Complaint
`complaint_code`, `student`, `category`, `subject`, `description`, `department_or_location`, `student_urgency`, `status`, `spam_score`, `spam_classification`, `is_confidential`, `director_public_remark`, `director_internal_note`, `created_at`, `updated_at`, `resolved_at`.

### Attachment
`complaint`, `storage_path`, `original_filename`, `content_type`, `size_bytes`, `uploaded_at`.

### ComplaintStatusHistory
`complaint`, `old_status`, `new_status`, `changed_by`, `remark`, `created_at`.

### SpamAnalysis
Component scores, final score, classification, JSON reasons, model/rules version, timestamp.

### AuditLog
Actor, action, target, metadata and timestamp for security-relevant administrative changes.

## Security requirements
- Director authorization is enforced in Django, not by hiding links.
- Students can query only their own complaints.
- Direct URL access to `/director/` by students is denied.
- CSRF remains enabled; passwords use Django hashing.
- Secrets are environment variables and `.env` is ignored.
- Production uses HTTPS and secure cookies.
- Attachments are private and validated for size/type.
- Internal Director notes are never exposed to students.
- Login and complaint submission are rate-limited.

## Confidential complaints
Support **verified-but-confidential** complaints: the system retains the verified student relationship while identity is restricted to specifically authorized personnel. Do not label this anonymous unless true anonymity is later engineered.

## Repository layout
```text
campusresolve/
├── manage.py
├── CLAUDE.md
├── README.md
├── ARCHITECTURE.md
├── IMPLEMENTATION.md
├── requirements.txt
├── .env.example
├── config/
├── apps/
│   ├── accounts/
│   ├── complaints/
│   ├── director_portal/
│   ├── spam_detection/
│   └── audit/
├── templates/
├── static/
└── tests/
```

## MVP acceptance criteria
1. Student registers and logs in.
2. Student submits a complaint that persists in Supabase PostgreSQL.
3. Student can see only their own complaint(s).
4. Director logs in and sees all complaints.
5. Student cannot access Director routes, including forged GET/POST requests.
6. Director changes status and adds a public remark.
7. Student sees the update.
8. Status history is recorded.
9. Basic spam analysis is stored and visible to Director.
10. Permission and core workflow tests pass.

## Local setup
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# copy .env.example to .env and fill Supabase DB values
python manage.py migrate
python manage.py seed_categories
python manage.py createsuperuser
python manage.py runserver
```

## Future enhancements
OTP/mobile verification, email/SMS notifications, departmental routing, SLA/escalation, student feedback, multilingual UI, mobile client, richer ML classification and AI-assisted categorization. These come **after** the secure MVP.
