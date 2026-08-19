from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from .forms import AttachmentUploadForm, ComplaintForm
from .models import Attachment, Complaint, Status
from .services import create_complaint
from .storage import AttachmentValidationError, get_authorized_file_url, save_attachment_file


@login_required
def dashboard(request):
    complaints = Complaint.objects.filter(student=request.user)
    counts = {
        "total": complaints.count(),
        "submitted": complaints.filter(status=Status.SUBMITTED).count(),
        "under_review": complaints.filter(status=Status.UNDER_REVIEW).count(),
        "in_progress": complaints.filter(status=Status.IN_PROGRESS).count(),
        "resolved": complaints.filter(status=Status.RESOLVED).count(),
    }
    recent = complaints[:5]
    return render(request, "complaints/dashboard.html", {"counts": counts, "recent": recent})


@login_required
def complaint_list(request):
    # Ownership-scoped: a student can only ever see complaints where
    # student=request.user (ARCHITECTURE.md section 2). Never fetch broader
    # and filter in the template.
    complaints = Complaint.objects.filter(student=request.user).select_related("category")
    status_filter = request.GET.get("status")
    if status_filter in dict(Status.choices):
        complaints = complaints.filter(status=status_filter)
    return render(
        request,
        "complaints/list.html",
        {"complaints": complaints, "statuses": Status.choices, "status_filter": status_filter},
    )


@login_required
def complaint_create(request):
    if request.method == "POST":
        form = ComplaintForm(request.POST)
        if form.is_valid():
            complaint = create_complaint(
                student=request.user,
                category=form.cleaned_data["category"],
                subject=form.cleaned_data["subject"],
                description=form.cleaned_data["description"],
                department_or_location=form.cleaned_data["department_or_location"],
                student_urgency=form.cleaned_data["student_urgency"],
                is_confidential=form.cleaned_data["is_confidential"],
            )
            messages.success(request, f"Complaint {complaint.complaint_code} submitted.")
            return redirect("complaints:detail", public_id=complaint.complaint_code)
    else:
        form = ComplaintForm()
    return render(request, "complaints/create.html", {"form": form})


@login_required
def complaint_detail(request, public_id):
    # Ownership-scoped lookup - never fetch an arbitrary complaint and hide
    # fields afterward (ARCHITECTURE.md section 2). A student changing the
    # URL to another student's complaint code gets a 404, not a 403 (avoids
    # confirming the code exists).
    complaint = get_object_or_404(
        Complaint.objects.select_related("category").prefetch_related("status_history", "attachments"),
        complaint_code=public_id,
        student=request.user,
    )
    upload_form = AttachmentUploadForm()
    return render(request, "complaints/detail.html", {"complaint": complaint, "upload_form": upload_form})


@login_required
def attachment_upload(request, public_id):
    # Ownership-scoped: only the owning student may attach evidence to their
    # own complaint (Phase 9).
    complaint = get_object_or_404(Complaint, complaint_code=public_id, student=request.user)

    if request.method == "POST":
        form = AttachmentUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data["file"]
            try:
                storage_path = save_attachment_file(complaint, uploaded_file)
            except AttachmentValidationError as exc:
                messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
                return redirect("complaints:detail", public_id=public_id)

            Attachment.objects.create(
                complaint=complaint,
                storage_path=storage_path,
                original_filename=uploaded_file.name,
                content_type=uploaded_file.content_type,
                size_bytes=uploaded_file.size,
            )
            messages.success(request, "Attachment uploaded.")
        else:
            messages.error(request, "Please choose a valid file.")
    return redirect("complaints:detail", public_id=public_id)


@login_required
def attachment_download(request, attachment_id):
    attachment = get_object_or_404(Attachment.objects.select_related("complaint"), pk=attachment_id)
    complaint = attachment.complaint

    # Authorization check BEFORE issuing any URL: owning student, or a
    # Director/Admin. This is the "ownership/role check before access" rule
    # from ARCHITECTURE.md section 7 / CLAUDE.md rule #7.
    is_owner = complaint.student_id == request.user.id
    is_director_or_admin = request.user.is_director or request.user.is_admin_role
    if not (is_owner or is_director_or_admin):
        raise PermissionDenied("You do not have access to this attachment.")

    url = get_authorized_file_url(attachment)
    return redirect(url)
