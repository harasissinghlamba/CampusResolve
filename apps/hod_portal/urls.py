from django.urls import path

from . import views

app_name = "hod_portal"

urlpatterns = [
    path("hod/", views.dashboard, name="dashboard"),
    path("hod/complaints/<int:pk>/", views.complaint_detail, name="complaint_detail"),
]
