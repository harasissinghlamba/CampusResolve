from django.contrib import admin

from .models import Attachment, Complaint, ComplaintCategory, ComplaintStatusHistory


@admin.register(ComplaintCategory)
class ComplaintCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    prepopulated_fields = {"slug": ("name",)}


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    readonly_fields = ("storage_path", "original_filename", "content_type", "size_bytes", "uploaded_at")


class StatusHistoryInline(admin.TabularInline):
    model = ComplaintStatusHistory
    extra = 0
    readonly_fields = ("old_status", "new_status", "changed_by", "remark", "created_at")


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ("complaint_code", "student", "category", "status", "spam_classification", "created_at")
    list_filter = ("status", "spam_classification", "category", "is_confidential")
    search_fields = ("complaint_code", "subject", "student__email", "student__roll_number")
    readonly_fields = ("complaint_code", "spam_score", "spam_classification", "created_at", "updated_at")
    inlines = [AttachmentInline, StatusHistoryInline]
