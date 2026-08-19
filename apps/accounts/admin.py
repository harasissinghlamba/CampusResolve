from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import LoginOTP, User


@admin.register(User)
class CampusResolveUserAdmin(UserAdmin):
    """
    Superusers can manage users here, but note: is_staff/is_superuser alone
    is NOT Director authorization in this app (see director_portal.permissions).
    The `role` field is the single source of truth for RBAC.
    """

    model = User
    list_display = ("email", "full_name", "role", "roll_number", "is_active", "date_joined")
    list_filter = ("role", "is_active", "phone_verified")
    search_fields = ("email", "full_name", "roll_number")
    ordering = ("-date_joined",)
    fieldsets = UserAdmin.fieldsets + (
        (
            "CampusResolve profile",
            {
                "fields": (
                    "role",
                    "full_name",
                    "roll_number",
                    "mobile_number",
                    "course",
                    "branch",
                    "semester",
                    "phone_verified",
                )
            },
        ),
    )


@admin.register(LoginOTP)
class LoginOTPAdmin(admin.ModelAdmin):
    # code_hash only - never expose or store the plaintext code anywhere.
    list_display = ("user", "purpose", "channel", "created_at", "expires_at", "attempts", "consumed")
    list_filter = ("purpose", "channel", "consumed")
    search_fields = ("user__email", "user__roll_number")
    readonly_fields = (
        "user", "purpose", "channel", "code_hash",
        "created_at", "expires_at", "attempts", "consumed",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
