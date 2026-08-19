from django.contrib import admin

from .models import SpamAnalysis


@admin.register(SpamAnalysis)
class SpamAnalysisAdmin(admin.ModelAdmin):
    list_display = ("complaint", "final_score", "classification", "created_at")
    list_filter = ("classification",)
    readonly_fields = [f.name for f in SpamAnalysis._meta.fields]

    def has_add_permission(self, request):
        return False
