"""
Centralized complaint status transition service (ARCHITECTURE.md section 4).
Views must call change_complaint_status() rather than setting
`complaint.status` directly, so transition rules and audit/history writes
live in exactly one place.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services import log_action

from .models import Complaint, ComplaintStatusHistory, Status

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Status.SUBMITTED: {Status.UNDER_REVIEW, Status.REJECTED, Status.SPAM},
    Status.UNDER_REVIEW: {Status.IN_PROGRESS, Status.REJECTED, Status.SPAM},
    Status.IN_PROGRESS: {Status.RESOLVED, Status.UNDER_REVIEW},
    Status.RESOLVED: {Status.CLOSED, Status.IN_PROGRESS},
    Status.REJECTED: set(),
    Status.SPAM: set(),
    Status.CLOSED: set(),
}


@transaction.atomic
def change_complaint_status(*, complaint: Complaint, new_status: str, actor, remark: str = "") -> Complaint:
    old_status = complaint.status

    if new_status not in dict(Status.choices):
        raise ValidationError(f"Unknown status: {new_status}")

    if new_status == old_status:
        raise ValidationError("Complaint is already in that status.")

    allowed = ALLOWED_TRANSITIONS.get(old_status, set())
    if new_status not in allowed:
        raise ValidationError(f"Cannot move complaint from {old_status} to {new_status}.")

    complaint.status = new_status
    if new_status == Status.RESOLVED:
        complaint.resolved_at = timezone.now()
    elif old_status == Status.RESOLVED and new_status == Status.IN_PROGRESS:
        # Reopened - clear the resolved timestamp.
        complaint.resolved_at = None
    complaint.save(update_fields=["status", "resolved_at", "updated_at"])

    ComplaintStatusHistory.objects.create(
        complaint=complaint,
        old_status=old_status,
        new_status=new_status,
        changed_by=actor,
        remark=remark,
    )

    log_action(
        actor=actor,
        action="COMPLAINT_STATUS_CHANGED",
        target=f"complaint:{complaint.pk}",
        metadata={"old_status": old_status, "new_status": new_status},
    )

    return complaint


@transaction.atomic
def create_complaint(*, student, category, subject: str, description: str,
                      department_or_location: str = "", student_urgency: str = "MEDIUM",
                      is_confidential: bool = False) -> Complaint:
    """
    Complaint creation service (ARCHITECTURE.md section 5 / Phase 5).

    `student` is always taken from the authenticated request, never from form
    input. Spam analysis runs as part of the same transaction as complaint
    creation, per CLAUDE.md engineering rules.
    """
    from apps.spam_detection.services import run_and_save_spam_analysis

    complaint = Complaint.objects.create(
        student=student,
        category=category,
        subject=subject,
        description=description,
        department_or_location=department_or_location,
        student_urgency=student_urgency,
        is_confidential=is_confidential,
        status=Status.SUBMITTED,
    )

    run_and_save_spam_analysis(complaint)

    ComplaintStatusHistory.objects.create(
        complaint=complaint,
        old_status="",
        new_status=Status.SUBMITTED,
        changed_by=student,
        remark="Complaint submitted.",
    )

    log_action(actor=student, action="COMPLAINT_CREATED", target=f"complaint:{complaint.pk}")

    return complaint


@transaction.atomic
def forward_complaint_to_department(*, complaint: Complaint, department: str, actor) -> Complaint:
    """
    Director-only action (enforced in the view, not here) that routes a
    complaint to the HOD of `department`. The HOD who picks this up never
    sees the student's identity - see hod_portal.views, which strips
    student fields out of the context entirely rather than merely hiding
    them in a template.
    """
    complaint.assigned_department = department
    complaint.assigned_at = timezone.now()
    complaint.assigned_by = actor
    complaint.save(update_fields=["assigned_department", "assigned_at", "assigned_by"])

    log_action(
        actor=actor,
        action="COMPLAINT_FORWARDED_TO_HOD",
        target=f"complaint:{complaint.pk}",
        metadata={"department": department},
    )
    return complaint
