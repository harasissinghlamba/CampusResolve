"""
OTP-verified student registration.

The gate being tested: a newly registered account is created with
is_active=False and is NOT usable until the emailed/texted code is
verified. Because Django's ModelBackend refuses to authenticate inactive
users, that check is enforced by Django itself - not merely by our views -
so these tests assert real behaviour, not cosmetics.
"""
import re
import unittest
from unittest.mock import MagicMock, patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import LoginOTP, OTPChannel, OTPPurpose, Role, User

try:  # twilio is only needed for the SMS channel
    import twilio  # noqa: F401

    TWILIO_INSTALLED = True
except ImportError:
    TWILIO_INSTALLED = False

requires_twilio = unittest.skipUnless(
    TWILIO_INSTALLED, "twilio not installed (pip install -r requirements.txt)"
)

TWILIO_SETTINGS = dict(
    SMS_OTP_ENABLED=True,
    TWILIO_ACCOUNT_SID="AC_test",
    TWILIO_AUTH_TOKEN="test_token",
    TWILIO_FROM_NUMBER="+15551234567",
)

VALID_SIGNUP = {
    "full_name": "New Student",
    "roll_number": "R900",
    "email": "new.student@campus.edu",
    "mobile_number": "+919876543210",
    "course": "BTech",
    "branch": "CSE",
    "semester": 3,
    "password1": "verystrongpass1",
    "password2": "verystrongpass1",
}


def _code_from_last_email() -> str:
    body = mail.outbox[-1].body
    match = re.search(r"code is: (\d{6})", body)
    assert match, f"Could not find code in email body: {body}"
    return match.group(1)


class RegistrationOTPFlowTests(TestCase):
    def setUp(self):
        mail.outbox = []

    def _register(self, **overrides):
        data = {**VALID_SIGNUP, **overrides}
        return self.client.post(reverse("accounts:register"), data=data)

    # --- step 1: signing up creates an INACTIVE account -------------------

    def test_registration_creates_inactive_user_and_sends_code(self):
        response = self._register()
        self.assertRedirects(response, reverse("accounts:verify_registration"))

        user = User.objects.get(email="new.student@campus.edu")
        self.assertFalse(user.is_active, "account must stay inactive until verified")
        self.assertEqual(user.role, Role.STUDENT)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("new.student@campus.edu", mail.outbox[0].to)

    def test_registration_does_not_log_the_user_in(self):
        self._register()
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_registration_issues_a_registration_scoped_otp(self):
        self._register()
        otp = LoginOTP.objects.latest("created_at")
        self.assertEqual(otp.purpose, OTPPurpose.REGISTRATION)
        self.assertEqual(otp.channel, OTPChannel.EMAIL)

    def test_unverified_account_cannot_log_in(self):
        self._register()
        self.client.logout()
        response = self.client.post(reverse("accounts:login"), data={
            "username": "new.student@campus.edu", "password": "verystrongpass1",
        })
        # Django's ModelBackend rejects is_active=False -> form redisplays.
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    # --- step 2: verifying the code activates the account -----------------

    def test_correct_code_activates_account_and_logs_in(self):
        self._register()
        code = _code_from_last_email()

        response = self.client.post(reverse("accounts:verify_registration"), data={"code": code})
        self.assertRedirects(
            response, reverse("accounts:post_login_redirect"), fetch_redirect_response=False
        )

        user = User.objects.get(email="new.student@campus.edu")
        self.assertTrue(user.is_active)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_wrong_code_leaves_account_inactive(self):
        self._register()
        response = self.client.post(reverse("accounts:verify_registration"), data={"code": "000000"})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.get(email="new.student@campus.edu").is_active)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_expired_code_is_rejected(self):
        self._register()
        code = _code_from_last_email()
        otp = LoginOTP.objects.latest("created_at")
        otp.expires_at = otp.created_at  # already elapsed
        otp.save(update_fields=["expires_at"])

        self.client.post(reverse("accounts:verify_registration"), data={"code": code})
        self.assertFalse(User.objects.get(email="new.student@campus.edu").is_active)

    def test_registration_code_cannot_be_replayed_as_a_login_code(self):
        """A REGISTRATION code must not satisfy a LOGIN check."""
        from apps.accounts.otp import verify_otp

        self._register()
        code = _code_from_last_email()
        user = User.objects.get(email="new.student@campus.edu")

        self.assertFalse(verify_otp(user, code, purpose=OTPPurpose.LOGIN))
        # ...but it still works for the purpose it was issued for.
        self.assertTrue(verify_otp(user, code, purpose=OTPPurpose.REGISTRATION))

    def test_code_is_single_use(self):
        self._register()
        code = _code_from_last_email()
        self.client.post(reverse("accounts:verify_registration"), data={"code": code})
        self.client.logout()

        # The consumed code must not verify anything a second time.
        response = self.client.get(reverse("accounts:verify_registration"))
        self.assertRedirects(response, reverse("accounts:register"))

    def test_verify_page_unreachable_without_a_pending_registration(self):
        response = self.client.get(reverse("accounts:verify_registration"))
        self.assertRedirects(response, reverse("accounts:register"))

    def test_otp_never_stored_in_plaintext(self):
        self._register()
        code = _code_from_last_email()
        otp = LoginOTP.objects.latest("created_at")
        self.assertNotEqual(otp.code_hash, code)
        self.assertNotIn(code, otp.code_hash)

    # --- resend -----------------------------------------------------------

    @override_settings(OTP_RESEND_COOLDOWN_SECONDS=0)
    def test_resend_issues_a_new_code_and_invalidates_the_old_one(self):
        self._register()
        first_code = _code_from_last_email()

        self.client.post(reverse("accounts:verify_registration"), data={"resend": "1"})
        self.assertEqual(len(mail.outbox), 2)

        # Old code is dead; the new one works.
        self.client.post(reverse("accounts:verify_registration"), data={"code": first_code})
        self.assertFalse(User.objects.get(email="new.student@campus.edu").is_active)

        self.client.post(
            reverse("accounts:verify_registration"), data={"code": _code_from_last_email()}
        )
        self.assertTrue(User.objects.get(email="new.student@campus.edu").is_active)

    def test_resend_respects_cooldown(self):
        self._register()
        self.client.post(reverse("accounts:verify_registration"), data={"resend": "1"})
        # Cooldown is 30s by default, so the second send is refused.
        self.assertEqual(len(mail.outbox), 1)

    # --- role injection is still impossible at signup ---------------------

    def test_registration_cannot_self_assign_a_privileged_role(self):
        self._register(role="DIRECTOR", is_staff="1", is_superuser="1")
        user = User.objects.get(email="new.student@campus.edu")
        self.assertEqual(user.role, Role.STUDENT)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)


class RegistrationSMSChannelTests(TestCase):
    def setUp(self):
        mail.outbox = []

    def _register_via_sms(self):
        return self.client.post(
            reverse("accounts:register"), data={**VALID_SIGNUP, "channel": "SMS"}
        )

    @requires_twilio
    @override_settings(**TWILIO_SETTINGS)
    @patch("twilio.rest.Client")
    def test_registration_via_sms_sends_text_not_email(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client

        response = self._register_via_sms()
        self.assertRedirects(response, reverse("accounts:verify_registration"))

        self.assertEqual(len(mail.outbox), 0, "SMS channel must not also send an email")
        mock_client.messages.create.assert_called_once()
        _, kwargs = mock_client.messages.create.call_args
        self.assertEqual(kwargs["to"], VALID_SIGNUP["mobile_number"])

        otp = LoginOTP.objects.latest("created_at")
        self.assertEqual(otp.channel, OTPChannel.SMS)

    @requires_twilio
    @override_settings(**TWILIO_SETTINGS)
    @patch("twilio.rest.Client")
    def test_sms_verification_sets_phone_verified(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        self._register_via_sms()

        # Recover the code Twilio was asked to send.
        _, kwargs = mock_client.messages.create.call_args
        code = re.search(r"code is: (\d{6})", kwargs["body"]).group(1)

        self.client.post(reverse("accounts:verify_registration"), data={"code": code})
        user = User.objects.get(email=VALID_SIGNUP["email"])
        self.assertTrue(user.is_active)
        self.assertTrue(user.phone_verified)

    @override_settings(SMS_OTP_ENABLED=False)
    def test_sms_channel_falls_back_safely_when_not_configured(self):
        """
        Requesting SMS with no Twilio config must not create a half-made
        account: the transaction rolls back and an error is shown.
        """
        response = self._register_via_sms()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email=VALID_SIGNUP["email"]).exists())

    @requires_twilio
    @override_settings(**TWILIO_SETTINGS)
    @patch("twilio.rest.Client")
    def test_twilio_failure_rolls_back_the_signup(self, mock_client_cls):
        from twilio.base.exceptions import TwilioRestException

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = TwilioRestException(
            status=401, uri="/Messages", msg="Authentication error", code=20003
        )
        mock_client_cls.return_value = mock_client

        response = self._register_via_sms()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            User.objects.filter(email=VALID_SIGNUP["email"]).exists(),
            "a failed delivery must not leave an unverifiable account behind",
        )


class EmailDeliveryFailureTests(TestCase):
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    @patch("apps.accounts.otp.send_mail")
    def test_smtp_auth_error_is_shown_not_raised(self, mock_send):
        """
        Regression test: SMTPAuthenticationError subclasses Exception, not
        OSError, so narrow exception handling used to let it escape as an
        unhandled 500. It must surface as a form error instead.
        """
        import smtplib

        mock_send.side_effect = smtplib.SMTPAuthenticationError(535, b"Bad credentials")

        response = self.client.post(reverse("accounts:register"), data=VALID_SIGNUP)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email=VALID_SIGNUP["email"]).exists())
