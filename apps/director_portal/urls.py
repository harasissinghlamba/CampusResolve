from django.urls import path

from . import views

app_name = "director_portal"

urlpatterns = [
    path("director/", views.dashboard, name="dashboard"),
    path("director/complaints/", views.complaint_list, name="complaint_list"),
    path("director/complaints/<int:pk>/", views.complaint_detail, name="complaint_detail"),
    path("director/spam-review/", views.spam_review, name="spam_review"),
    path("director/analytics/", views.analytics, name="analytics"),
]
