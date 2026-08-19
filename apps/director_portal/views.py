from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Avg, Count, ExpressionWrapper, F, DurationField, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.complaints.models import Complaint, ComplaintCategory, SpamClassification, Status
from apps.complaints.services import change_complaint_status, forward_complaint_to_department

from .forms import DirectorRemarkForm, ForwardToDepartmentForm, StatusChangeForm
from .permissions import director_required


@director_required
def dashboard(request):
    complaints = Complaint.objects.all()
    counts = {
        "total": complaints.count(),
        "submitted": complaints.filter(status=Status.SUBMITTED).count(),
        "under_review": complaints.filter(status=Status.UNDER_REVIEW).count(),
        "in_progress": complaints.filter(status=Status.IN_PROGRESS).count(),
        "resolved": complaints.filter(status=Status.RESOLVED).count(),
        "suspected_spam": complaints.filter(
            spam_classification__in=[SpamClassification.REVIEW, SpamClassification.SUSPICIOUS]
        ).count(),
    }
    recent = complaints.select_related("student", "category")[:8]
    return render(request, "director_portal/dashboard.html", {"counts": counts, "recent": recent})


@director_required
def complaint_list(request):
    complaints = Complaint.objects.select_related("student", "category").all()

    code = request.GET.get("code", "").strip()
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    status = request.GET.get("status", "")
    spam_classification = request.GET.get("spam_classification", "")

    if code:
        complaints = complaints.filter(complaint_code__icontains=code)
    if query:
        complaints = complaints.filter(
            Q(student__full_name__icontains=query) | Q(student__roll_number__icontains=query)
        )
    if category:
        complaints = complaints.filter(category__slug=category)
    if status in dict(Status.choices):
        complaints = complaints.filter(status=status)
    if spam_classification in dict(SpamClassification.choices):
        complaints = complaints.filter(spam_classification=spam_classification)

    context = {
        "complaints": complaints[:200],
        "categories": ComplaintCategory.objects.filter(is_active=True),
        "statuses": Status.choices,
        "spam_classifications": SpamClassification.choices,
        "filters": {
            "code": code, "q": query, "category": category,
            "status": status, "spam_classification": spam_classification,
        },
    }
    return render(request, "director_portal/complaint_list.html", context)


@director_required
def complaint_detail(request, pk):
    complaint = get_object_or_404(
        Complaint.objects.select_related("student", "category").prefetch_related(
            "status_history", "attachments", "spam_analysis"
        ),
        pk=pk,
    )

    status_form = StatusChangeForm(initial={"new_status": complaint.status})
    remark_form = DirectorRemarkForm(instance=complaint)
    forward_form = ForwardToDepartmentForm(initial={"department": complaint.assigned_department})

    if request.method == "POST":
        if "forward_complaint" in request.POST:
            forward_form = ForwardToDepartmentForm(request.POST)
            if forward_form.is_valid():
                forward_complaint_to_department(
                    complaint=complaint,
                    department=forward_form.cleaned_data["department"],
                    actor=request.user,
                )
                messages.success(
                    request,
                    f"Forwarded to the {forward_form.cleaned_data['department']} HOD. "
                    "Student identity is not shared with the HOD.",
                )
                return redirect("director_portal:complaint_detail", pk=pk)
        elif "change_status" in request.POST:
            status_form = StatusChangeForm(request.POST)
            if status_form.is_valid():
                try:
                    change_complaint_status(
                        complaint=complaint,
                        new_status=status_form.cleaned_data["new_status"],
                        actor=request.user,
                        remark=status_form.cleaned_data["remark"],
                    )
                    messages.success(request, "Status updated.")
                    return redirect("director_portal:complaint_detail", pk=pk)
                except ValidationError as exc:
                    status_form.add_error(None, exc.message if hasattr(exc, "message") else str(exc))
        elif "save_remarks" in request.POST:
            remark_form = DirectorRemarkForm(request.POST, instance=complaint)
            if remark_form.is_valid():
                remark_form.save()
                messages.success(request, "Remarks saved.")
                return redirect("director_portal:complaint_detail", pk=pk)

    return render(
        request,
        "director_portal/complaint_detail.html",
        {
            "complaint": complaint,
            "status_form": status_form,
            "remark_form": remark_form,
            "forward_form": forward_form,
        },
    )


@director_required
def spam_review(request):
    complaints = (
        Complaint.objects.select_related("student", "category", "spam_analysis")
        .filter(spam_classification__in=[SpamClassification.REVIEW, SpamClassification.SUSPICIOUS])
        .order_by("-spam_score", "-created_at")
    )
    return render(request, "director_portal/spam_review.html", {"complaints": complaints})


@director_required
def analytics(request):
    complaints = Complaint.objects.all()

    status_counts = list(complaints.values("status").annotate(count=Count("id")).order_by("status"))
    category_counts = list(
        complaints.values("category__name").annotate(count=Count("id")).order_by("-count")
    )
    spam_counts = list(
        complaints.values("spam_classification").annotate(count=Count("id")).order_by("spam_classification")
    )

    resolved = complaints.filter(resolved_at__isnull=False).annotate(
        resolution_time=ExpressionWrapper(F("resolved_at") - F("created_at"), output_field=DurationField())
    )
    avg_resolution = resolved.aggregate(avg=Avg("resolution_time"))["avg"]
    avg_resolution_hours = round(avg_resolution.total_seconds() / 3600, 1) if avg_resolution else None

    context = {
        "total": complaints.count(),
        "status_counts": status_counts,
        "category_counts": category_counts,
        "spam_counts": spam_counts,
        "avg_resolution_hours": avg_resolution_hours,
    }
    return render(request, "director_portal/analytics.html", context)
