import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.accounts.models import Department


class ComplaintCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=110, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "complaint categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Status(models.TextChoices):
    SUBMITTED = "SUBMITTED", "Submitted"
    UNDER_REVIEW = "UNDER_REVIEW", "Under review"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    RESOLVED = "RESOLVED", "Resolved"
    REJECTED = "REJECTED", "Rejected"
    SPAM = "SPAM", "Spam"
    CLOSED = "CLOSED", "Closed"


class Urgency(models.TextChoices):
    LOW = "LOW", "Low"
    MEDIUM = "MEDIUM", "Medium"
    HIGH = "HIGH", "High"


class SpamClassification(models.TextChoices):
    NORMAL = "NORMAL", "Normal"
    REVIEW = "REVIEW", "Review"
    SUSPICIOUS = "SUSPICIOUS", "Suspicious"


def _generate_complaint_code():
    year = timezone.now().year
    return f"CMP-{year}-{uuid.uuid4().hex[:6].upper()}"


class Complaint(models.Model):
    """
    NOTE: `complaint_code` is a human-readable reference only. It is never
    used for authorization - ownership checks always use `student=request.user`
    (see ARCHITECTURE.md section 2).
    """

    complaint_code = models.CharField(max_length=32, unique=True, default=_generate_complaint_code, editable=False)
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="complaints"
    )
    category = models.ForeignKey(
        ComplaintCategory, on_delete=models.PROTECT, related_name="complaints"
    )

    subject = models.CharField(max_length=200)
    description = models.TextField()
    department_or_location = models.CharField(max_length=200, blank=True)
    student_urgency = models.CharField(max_length=10, choices=Urgency.choices, default=Urgency.MEDIUM)

    status = models.CharField(max_length=15, choices=Status.choices, default=Status.SUBMITTED)

    # Denormalized summary of the latest SpamAnalysis, for cheap list-page display.
    spam_score = models.PositiveSmallIntegerField(default=0)
    spam_classification = models.CharField(
        max_length=12, choices=SpamClassification.choices, default=SpamClassification.NORMAL
    )

    is_confidential = models.BooleanField(default=False)
    director_public_remark = models.TextField(blank=True)
    director_internal_note = models.TextField(blank=True)

    # Director -> HOD forwarding. The assigned HOD never sees the student's
    # identity (name/roll/email) - only the complaint content - regardless
    # of `is_confidential`. See hod_portal.views.
    assigned_department = models.CharField(
        max_length=20, choices=Department.choices, null=True, blank=True
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="complaints_forwarded",
    )
    hod_remark = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["student", "created_at"]),
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["category", "created_at"]),
            models.Index(fields=["spam_classification", "created_at"]),
            models.Index(fields=["assigned_department", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.complaint_code} ({self.status})"


class Attachment(models.Model):
    """
    Only metadata lives in PostgreSQL; bytes live in private Supabase Storage
    (or local media/ in dev). `storage_path` is a server-generated UUID path,
    never derived from the original filename.
    """

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="attachments")
    storage_path = models.CharField(max_length=512, unique=True)
    original_filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.original_filename


class ComplaintStatusHistory(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name="status_history")
    old_status = models.CharField(max_length=15, choices=Status.choices, blank=True)
    new_status = models.CharField(max_length=15, choices=Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="status_changes"
    )
    remark = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.complaint.complaint_code}: {self.old_status} -> {self.new_status}"
