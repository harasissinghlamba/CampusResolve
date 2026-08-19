import re

from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import LoginOTP
from apps.accounts.otp import can_resend, generate_and_send_otp

from .test_authorization import make_director, make_student


def _extract_code_from_last_email() -> str:
    body = mail.outbox[-1].body
    match = re.search(r"code is: (\d{6})", body)
    assert match, f"Could not find code in email body: {body}"
    return match.group(1)


class StudentLoginOTPTests(TestCase):
    def setUp(self):
        self.student = make_student("otp.student@campus.edu", "R700")
        self.student.set_password("correcthorse123")
        self.student.save()

    def test_student_login_does_not_authenticate_immediately(self):
        response = self.client.post(reverse("accounts:login"), data={
            "username": "otp.student@campus.edu", "password": "correcthorse123",
        })
        self.assertRedirects(response, reverse("accounts:verify_otp"))
        # Session should NOT be authenticated yet.
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("otp.student@campus.edu", mail.outbox[0].to)

    def test_correct_code_completes_login(self):
        self.client.post(reverse("accounts:login"), data={
            "username": "otp.student@campus.edu", "password": "correcthorse123",
        })
        code = _extract_code_from_last_email()
        response = self.client.post(reverse("accounts:verify_otp"), data={"code": code})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:post_login_redirect"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.student.pk)

    def test_wrong_code_rejected_and_does_not_authenticate(self):
        self.client.post(reverse("accounts:login"), data={
            "username": "otp.student@campus.edu", "password": "correcthorse123",
        })
        response = self.client.post(reverse("accounts:verify_otp"), data={"code": "000000"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_code_is_single_use(self):
        self.client.post(reverse("accounts:login"), data={
            "username": "otp.student@campus.edu", "password": "correcthorse123",
        })
        code = _extract_code_from_last_email()
        self.client.post(reverse("accounts:verify_otp"), data={"code": code})
        self.client.logout()

        # Log in again, get a fresh OTP flow, and try re-using the OLD code.
        self.client.post(reverse("accounts:login"), data={
            "username": "otp.student@campus.edu", "password": "correcthorse123",
        })
        response = self.client.post(reverse("accounts:verify_otp"), data={"code": code})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_too_many_wrong_attempts_locks_the_code(self):
        with self.settings(OTP_MAX_ATTEMPTS=2):
            self.client.post(reverse("accounts:login"), data={
                "username": "otp.student@campus.edu", "password": "correcthorse123",
            })
            code = _extract_code_from_last_email()
            self.client.post(reverse("accounts:verify_otp"), data={"code": "111111"})
            self.client.post(reverse("accounts:verify_otp"), data={"code": "222222"})
            # Attempts exhausted - even the correct code should no longer work.
            response = self.client.post(reverse("accounts:verify_otp"), data={"code": code})
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_resend_cooldown_enforced(self):
        self.assertTrue(can_resend(self.student))
        generate_and_send_otp(self.student)
        self.assertFalse(can_resend(self.student))

    def test_resend_sends_new_email(self):
        self.client.post(reverse("accounts:login"), data={
            "username": "otp.student@campus.edu", "password": "correcthorse123",
        })
        with self.settings(OTP_RESEND_COOLDOWN_SECONDS=0):
            self.client.post(reverse("accounts:verify_otp"), data={"resend": "1"})
        self.assertEqual(len(mail.outbox), 2)

    def test_otp_never_stored_in_plaintext(self):
        generate_and_send_otp(self.student)
        code = _extract_code_from_last_email()
        otp = LoginOTP.objects.filter(user=self.student).latest("created_at")
        self.assertNotEqual(otp.code_hash, code)
        self.assertNotIn(code, otp.code_hash)

    def test_director_login_skips_otp_entirely(self):
        director = make_director("otp.director@campus.edu")
        director.set_password("directorpass1")
        director.save()

        response = self.client.post(reverse("accounts:login"), data={
            "username": "otp.director@campus.edu", "password": "directorpass1",
        })
        self.assertEqual(int(self.client.session["_auth_user_id"]), director.pk)
        self.assertEqual(len(mail.outbox), 0)

    def test_verify_otp_page_unreachable_without_pending_login(self):
        response = self.client.get(reverse("accounts:verify_otp"))
        self.assertRedirects(response, reverse("accounts:login"))
