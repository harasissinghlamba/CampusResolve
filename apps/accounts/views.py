from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy

from apps.audit.services import log_action

from .forms import EmailAuthenticationForm, OTPVerifyForm, StudentRegistrationForm
from .models import OTPChannel, OTPPurpose, Role, User
from .otp import (
    OTPDeliveryError,
    can_resend,
    generate_and_send_otp,
    mask_email,
    mask_phone,
    seconds_until_resend,
    verify_otp,
)

# Session keys. Both hold only a user PK - never a password, never a code.
SESSION_LOGIN_OTP_USER = "pending_otp_user_id"
SESSION_REGISTRATION_OTP_USER = "pending_registration_user_id"
SESSION_REGISTRATION_CHANNEL = "pending_registration_channel"


def _requested_channel(request) -> str:
    """Read a user-supplied channel safely - never trust the raw POST value."""
    choice = request.POST.get("channel", OTPChannel.EMAIL)
    return choice if choice in OTPChannel.values else OTPChannel.EMAIL


def register(request):
    """
    Step 1 of registration. Creates the Student with is_active=False and
    sends a verification code; the account is NOT usable until
    verify_registration() succeeds. Nothing is logged in here.
    """
    if request.user.is_authenticated:
        return redirect("accounts:post_login_redirect")

    if request.method == "POST":
        form = StudentRegistrationForm(request.POST)
        if form.is_valid():
            channel = _requested_channel(request)

            # The user row and its first OTP are created together - if
            # delivery fails we roll the whole thing back rather than
            # leaving an unverifiable orphan account behind.
            try:
                with transaction.atomic():
                    user = form.save()  # is_active=False, set in the form
                    generate_and_send_otp(
                        user, purpose=OTPPurpose.REGISTRATION, channel=channel
                    )
            except OTPDeliveryError as exc:
                messages.error(request, str(exc))
                return render(
                    request,
                    "accounts/register.html",
                    {"form": form, "sms_available": settings.SMS_OTP_ENABLED},
                )

            log_action(
                actor=user,
                action="STUDENT_REGISTERED_PENDING_VERIFICATION",
                target=f"user:{user.pk}",
                metadata={"channel": channel},
            )
            request.session[SESSION_REGISTRATION_OTP_USER] = user.pk
            request.session[SESSION_REGISTRATION_CHANNEL] = channel
            return redirect("accounts:verify_registration")
    else:
        form = StudentRegistrationForm()

    return render(
        request,
        "accounts/register.html",
        {"form": form, "sms_available": settings.SMS_OTP_ENABLED},
    )


def verify_registration(request):
    """
    Step 2 of registration. Only reachable mid-signup via the
    `pending_registration_user_id` session key. On success the account is
    activated (is_active=True) and the student is logged straight in.
    """
    user_id = request.session.get(SESSION_REGISTRATION_OTP_USER)
    if not user_id:
        return redirect("accounts:register")

    # Scoped to inactive students only: once verified, this view can't be
    # replayed to re-verify or to touch anybody else's account.
    user = get_object_or_404(User, pk=user_id, role=Role.STUDENT, is_active=False)
    channel = request.session.get(SESSION_REGISTRATION_CHANNEL, OTPChannel.EMAIL)
    form = OTPVerifyForm()

    if request.method == "POST":
        if "resend" in request.POST:
            new_channel = _requested_channel(request)
            if not can_resend(user, purpose=OTPPurpose.REGISTRATION):
                wait = seconds_until_resend(user, purpose=OTPPurpose.REGISTRATION)
                messages.error(request, f"Please wait {wait}s before requesting another code.")
            else:
                try:
                    # Atomic so a failed send rolls back the supersession -
                    # the student keeps whatever code they already had.
                    with transaction.atomic():
                        generate_and_send_otp(
                            user, purpose=OTPPurpose.REGISTRATION, channel=new_channel
                        )
                    request.session[SESSION_REGISTRATION_CHANNEL] = new_channel
                    messages.success(
                        request,
                        "A new code has been sent by SMS."
                        if new_channel == OTPChannel.SMS
                        else "A new code has been sent to your email.",
                    )
                except OTPDeliveryError as exc:
                    messages.error(request, str(exc))
            return redirect("accounts:verify_registration")

        form = OTPVerifyForm(request.POST)
        if form.is_valid():
            if verify_otp(user, form.cleaned_data["code"], purpose=OTPPurpose.REGISTRATION):
                with transaction.atomic():
                    user.is_active = True
                    if channel == OTPChannel.SMS:
                        user.phone_verified = True
                    user.save(update_fields=["is_active", "phone_verified"])

                del request.session[SESSION_REGISTRATION_OTP_USER]
                request.session.pop(SESSION_REGISTRATION_CHANNEL, None)
                log_action(
                    actor=user,
                    action="STUDENT_REGISTRATION_VERIFIED",
                    target=f"user:{user.pk}",
                    metadata={"channel": channel},
                )
                auth_login(request, user)
                messages.success(request, "Your account is verified. Welcome to CampusResolve!")
                return redirect("accounts:post_login_redirect")

            messages.error(
                request, "Incorrect or expired code. Please try again, or resend a new one."
            )

    destination = mask_phone(user.mobile_number) if channel == OTPChannel.SMS else mask_email(user.email)
    return render(
        request,
        "accounts/verify_registration.html",
        {
            "form": form,
            "channel": channel,
            "destination": destination,
            "otp_length": settings.OTP_LENGTH,
            "otp_box_range": range(settings.OTP_LENGTH),
            "resend_wait": seconds_until_resend(user, purpose=OTPPurpose.REGISTRATION),
            "sms_available": settings.SMS_OTP_ENABLED and bool(user.mobile_number),
        },
    )


class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()

        if user.role == Role.STUDENT:
            # Students get an extra OTP step before the session is actually
            # established - auth_login() is NOT called yet.
            try:
                generate_and_send_otp(user, purpose=OTPPurpose.LOGIN, channel=OTPChannel.EMAIL)
            except OTPDeliveryError as exc:
                messages.error(self.request, str(exc))
                return self.form_invalid(form)

            self.request.session[SESSION_LOGIN_OTP_USER] = user.pk
            messages.info(
                self.request, f"We've emailed a verification code to {mask_email(user.email)}."
            )
            return redirect("accounts:verify_otp")

        auth_login(self.request, user)
        return redirect(self.get_success_url())


class EmailLogoutView(LogoutView):
    next_page = reverse_lazy("accounts:login")


@login_required
def post_login_redirect(request):
    """
    Role-aware redirect after login. This is a UX convenience only - it is
    NOT a security boundary. Actual authorization is enforced independently
    on every protected view (see director_portal.permissions).
    """
    if request.user.is_director or request.user.is_admin_role:
        return redirect("director_portal:dashboard")
    if request.user.is_hod:
        return redirect("hod_portal:dashboard")
    return redirect("complaints:dashboard")


def verify_otp_view(request):
    """
    Phase 13: the code-entry step for student logins. Only reachable
    mid-login, via the `pending_otp_user_id` session key set by
    EmailLoginView above - a Student can't jump straight here and no
    session is established until the correct code is entered.
    """
    user_id = request.session.get(SESSION_LOGIN_OTP_USER)
    if not user_id:
        return redirect("accounts:login")
    user = get_object_or_404(User, pk=user_id, role=Role.STUDENT, is_active=True)

    form = OTPVerifyForm()

    if request.method == "POST":
        if "resend" in request.POST:
            channel = _requested_channel(request)
            if not can_resend(user, purpose=OTPPurpose.LOGIN):
                wait = seconds_until_resend(user, purpose=OTPPurpose.LOGIN)
                messages.error(request, f"Please wait {wait}s before requesting another code.")
            else:
                try:
                    with transaction.atomic():
                        generate_and_send_otp(user, purpose=OTPPurpose.LOGIN, channel=channel)
                    messages.success(request, "A new code has been sent.")
                except OTPDeliveryError as exc:
                    messages.error(request, str(exc))
            return redirect("accounts:verify_otp")

        form = OTPVerifyForm(request.POST)
        if form.is_valid():
            if verify_otp(user, form.cleaned_data["code"], purpose=OTPPurpose.LOGIN):
                del request.session[SESSION_LOGIN_OTP_USER]
                auth_login(request, user)
                log_action(actor=user, action="STUDENT_LOGIN_OTP_VERIFIED", target=f"user:{user.pk}")
                return redirect("accounts:post_login_redirect")
            messages.error(
                request, "Incorrect or expired code. Please try again, or resend a new one."
            )

    return render(
        request,
        "accounts/verify_otp.html",
        {
            "form": form,
            "email": mask_email(user.email),
            "otp_length": settings.OTP_LENGTH,
            "otp_box_range": range(settings.OTP_LENGTH),
            "sms_available": settings.SMS_OTP_ENABLED and bool(user.mobile_number),
        },
    )
