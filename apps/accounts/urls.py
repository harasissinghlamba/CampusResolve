from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("verify-registration/", views.verify_registration, name="verify_registration"),
    path("login/", views.EmailLoginView.as_view(), name="login"),
    path("logout/", views.EmailLogoutView.as_view(), name="logout"),
    path("verify-otp/", views.verify_otp_view, name="verify_otp"),
    path("post-login/", views.post_login_redirect, name="post_login_redirect"),
]
