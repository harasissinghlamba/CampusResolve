from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(pattern_name="accounts:login", permanent=False), name="home"),
    path("accounts/", include("apps.accounts.urls")),
    path("", include("apps.complaints.urls")),
    path("", include("apps.director_portal.urls")),
    path("", include("apps.hod_portal.urls")),
]
