"""
Student OTP service - used for both login verification (Phase 13) and
new-account verification at registration.

Delivery is isolated behind _deliver(), which dispatches to email
(django.core.mail) or SMS (Twilio). Adding another provider means changing
that one function - not the login flow, the model, or the views.

Security properties:
  - purpose-scoped:     a REGISTRATION code can never satisfy a LOGIN check
                         (and vice versa) - lookups always filter on purpose
  - expiration:         LoginOTP.expires_at, checked in is_still_usable()
  - attempt limits:     LoginOTP.attempts, capped by OTP_MAX_ATTEMPTS
  - single use:         LoginOTP.consumed, set the moment a code validates
  - supersession:       issuing a new code consumes any outstanding code for
                         the same user+purpose, so only the newest is live
  - resend cooldown:    can_resend() below
  - safe storage:       only make_password(code) is ever persisted
  - never logged:       the plaintext code exists only in this module's
                         local scope and the outgoing message body - it is
                         never passed to log_action()/AuditLog, and
                         audit.services already strips any "otp" key as a
                         second line of defense.

Delivery failures NEVER propagate as raw exceptions. Everything is caught
and re-raised as OTPDeliveryError with a user-safe message, so a
misconfigured SMTP password or Twilio key produces a readable on-screen
error instead of an unhandled 500. (smtplib.SMTPAuthenticationError
subclasses Exception, not OSError, so catching OSError alone is not
enough - that was a real bug in an earlier revision of this file.)
"""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.utils import timezone

from .models import LoginOTP, OTPChannel, OTPPurpose

logger = logging.getLogger(__name__)


class OTPDeliveryError(Exception):
    """A code could not be delivered. Message is safe to show to the user."""


def _generate_numeric_code(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def mask_email(email: str) -> str:
    """j***n@college.edu - never render a full address on the verify screen."""
    try:
        local, domain = email.split("@", 1)
    except ValueError:
        return email
    if len(local) <= 2:
        return f"{local[0]}*@{domain}"
    return f"{local[0]}{'*' * (len(local) - 2)}{local[-1]}@{domain}"


def mask_phone(number: str) -> str:
    """*******3210 - never render a full number on the verify screen."""
    digits = (number or "").strip()
    if len(digits) <= 4:
        return "*" * len(digits)
    return "*" * (len(digits) - 4) + digits[-4:]


def _message_body(code: str, purpose: str) -> str:
    # NB: the "... code is: <digits>" shape is relied on by tests that parse
    # the code out of mail.outbox - keep that substring intact if reworded.
    label = (
        "CampusResolve account verification code"
        if purpose == OTPPurpose.REGISTRATION
        else "CampusResolve login verification code"
    )
    return (
        f"Your {label} is: {code}\n\n"
        f"This code expires in {settings.OTP_EXPIRY_MINUTES} minutes and can only be used once. "
        "Never share this code with anyone, including CampusResolve staff."
    )


def _deliver_email(user, code: str, purpose: str) -> None:
    subject = (
        "Verify your CampusResolve account"
        if purpose == OTPPurpose.REGISTRATION
        else "Your CampusResolve login code"
    )
    try:
        send_mail(
            subject=subject,
            message=_message_body(code, purpose),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception as exc:  # broad on purpose - see module docstring
        logger.warning("OTP email delivery failed (%s): %s", type(exc).__name__, exc)
        raise OTPDeliveryError(
            "We couldn't send the verification email. Please try again shortly, or ask "
            "your administrator to check the EMAIL_* settings."
        ) from exc


def _deliver_sms(user, code: str, purpose: str) -> None:
    if not settings.SMS_OTP_ENABLED:
        raise OTPDeliveryError(
            "SMS verification isn't configured on this server (missing TWILIO_* settings). "
            "Please use email instead."
        )
    if not user.mobile_number:
        raise OTPDeliveryError("There's no mobile number on this account. Please use email instead.")

    try:
        from twilio.base.exceptions import TwilioRestException
        from twilio.rest import Client
    except ImportError as exc:
        logger.warning("SMS OTP requested but the 'twilio' package is not installed.")
        raise OTPDeliveryError(
            "SMS verification isn't available right now. Please use email instead."
        ) from exc

    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(
            to=user.mobile_number,
            from_=settings.TWILIO_FROM_NUMBER,
            body=_message_body(code, purpose),
        )
    except TwilioRestException as exc:
        logger.warning("OTP SMS delivery failed (Twilio %s): %s", exc.code, exc.msg)
        raise OTPDeliveryError(
            "We couldn't send the SMS code. Please try email instead."
        ) from exc
    except Exception as exc:  # network errors, bad config, etc.
        logger.warning("OTP SMS delivery failed (%s): %s", type(exc).__name__, exc)
        raise OTPDeliveryError(
            "We couldn't send the SMS code. Please try email instead."
        ) from exc


def generate_and_send_otp(
    user,
    *,
    purpose: str = OTPPurpose.LOGIN,
    channel: str = OTPChannel.EMAIL,
) -> LoginOTP:
    """
    Consume any outstanding code for this user+purpose, issue a fresh one,
    and deliver it. Returns the LoginOTP row - never the plaintext code.

    Raises OTPDeliveryError (and only that) if delivery fails.
    """
    LoginOTP.objects.filter(user=user, purpose=purpose, consumed=False).update(consumed=True)

    code = _generate_numeric_code(settings.OTP_LENGTH)
    otp = LoginOTP.objects.create(
        user=user,
        purpose=purpose,
        channel=channel,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
    )

    if channel == OTPChannel.SMS:
        _deliver_sms(user, code, purpose)
    else:
        _deliver_email(user, code, purpose)

    return otp


def verify_otp(user, submitted_code: str, *, purpose: str = OTPPurpose.LOGIN) -> bool:
    otp = (
        LoginOTP.objects.filter(user=user, purpose=purpose, consumed=False)
        .order_by("-created_at")
        .first()
    )
    if not otp or not otp.is_still_usable(settings.OTP_MAX_ATTEMPTS):
        return False

    otp.attempts += 1
    otp.save(update_fields=["attempts"])

    if check_password(submitted_code.strip(), otp.code_hash):
        otp.consumed = True
        otp.save(update_fields=["consumed"])
        return True
    return False


def can_resend(user, *, purpose: str = OTPPurpose.LOGIN) -> bool:
    latest = LoginOTP.objects.filter(user=user, purpose=purpose).order_by("-created_at").first()
    if not latest:
        return True
    return timezone.now() >= latest.created_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)


def seconds_until_resend(user, *, purpose: str = OTPPurpose.LOGIN) -> int:
    latest = LoginOTP.objects.filter(user=user, purpose=purpose).order_by("-created_at").first()
    if not latest:
        return 0
    remaining = (
        latest.created_at + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
    ) - timezone.now()
    return max(0, int(remaining.total_seconds()))
