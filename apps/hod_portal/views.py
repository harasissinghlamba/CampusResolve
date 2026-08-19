from django.contrib import messages
from django.core.exceptions import ValidationError, PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from apps.complaints.models import Complaint
from apps.complaints.services import change_complaint_status

from .forms import HodRemarkForm, HodStatusChangeForm
from .permissions import hod_required


def _complaint_summary(complaint):
    """
    Build a plain dict with ONLY non-identifying fields. Deliberately not
    passing the Complaint model instance itself to HOD templates - a bare
    dict has no `.student` relation for a template to accidentally follow,
    so identity cannot leak even via a future template edit mistake.
    """
    return {
        "id": complaint.id,
        "complaint_code": complaint.complaint_code,
        "category": complaint.category.name,
        "subject": complaint.subject,
        "description": complaint.description,
        "department_or_location": complaint.department_or_location,
        "student_urgency": complaint.student_urgency,
        "status": complaint.status,
        "assigned_at": complaint.assigned_at,
        "hod_remark": complaint.hod_remark,
        "created_at": complaint.created_at,
        "status_history": [
            {"new_status": h.new_status, "created_at": h.created_at, "remark": h.remark}
            for h in complaint.status_history.all()
        ],
        "attachments": [
            {"id": a.id, "original_filename": a.original_filename}
            for a in complaint.attachments.all()
        ],
    }


@hod_required
def dashboard(request):
    complaints = (
        Complaint.objects.select_related("category")
        .filter(assigned_department=request.user.department)
        .order_by("-assigned_at")
    )
    summaries = [
        {
            "id": c.id, "complaint_code": c.complaint_code, "category": c.category.name,
            "subject": c.subject, "status": c.status, "assigned_at": c.assigned_at,
        }
        for c in complaints
    ]
    return render(request, "hod_portal/dashboard.html", {
        "complaints": summaries,
        "department": request.user.get_department_display(),
    })


@hod_required
def complaint_detail(request, pk):
    complaint = get_object_or_404(
        Complaint.objects.select_related("category").prefetch_related("status_history", "attachments"),
        pk=pk,
    )
    # Object-level check: this HOD may only act on complaints forwarded to
    # THEIR department, even if they guess another complaint's pk.
    if complaint.assigned_department != request.user.department:
        raise PermissionDenied("This complaint was not forwarded to your department.")

    status_form = HodStatusChangeForm(initial={"new_status": complaint.status})
    remark_form = HodRemarkForm(initial={"hod_remark": complaint.hod_remark})

    if request.method == "POST":
        if "change_status" in request.POST:
            status_form = HodStatusChangeForm(request.POST)
            if status_form.is_valid():
                try:
                    change_complaint_status(
                        complaint=complaint,
                        new_status=status_form.cleaned_data["new_status"],
                        actor=request.user,
                        remark=status_form.cleaned_data["remark"],
                    )
                    messages.success(request, "Status updated.")
                    return redirect("hod_portal:complaint_detail", pk=pk)
                except ValidationError as exc:
                    status_form.add_error(None, exc.message if hasattr(exc, "message") else str(exc))
        elif "save_remark" in request.POST:
            remark_form = HodRemarkForm(request.POST)
            if remark_form.is_valid():
                complaint.hod_remark = remark_form.cleaned_data["hod_remark"]
                complaint.save(update_fields=["hod_remark"])
                messages.success(request, "Remark saved.")
                return redirect("hod_portal:complaint_detail", pk=pk)

    return render(request, "hod_portal/complaint_detail.html", {
        "complaint": _complaint_summary(complaint),
        "status_form": status_form,
        "remark_form": remark_form,
    })
