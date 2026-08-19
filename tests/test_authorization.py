from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.complaints.models import Complaint, ComplaintCategory


def make_student(email="student1@campus.edu", roll="R001"):
    return User.objects.create_user(
        username=email, email=email, password="pass12345",
        full_name="Student One", roll_number=roll, role=Role.STUDENT,
    )


def make_director(email="director1@campus.edu"):
    return User.objects.create_user(
        username=email, email=email, password="pass12345",
        full_name="Director One", role=Role.DIRECTOR,
    )


def make_complaint(student, category):
    return Complaint.objects.create(
        student=student, category=category, subject="Broken tap", description="Water leaking in hostel block A."
    )


class AuthorizationMatrixTests(TestCase):
    """The mandatory Phase 14 access matrix."""

    def setUp(self):
        self.category = ComplaintCategory.objects.create(name="Hostel", slug="hostel")
        self.student_a = make_student("a@campus.edu", "R100")
        self.student_b = make_student("b@campus.edu", "R200")
        self.director = make_director()
        self.complaint_a = make_complaint(self.student_a, self.category)

    def test_anonymous_to_protected_student_page_denied(self):
        response = self.client.get(reverse("complaints:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_anonymous_to_director_denied(self):
        response = self.client.get(reverse("director_portal:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_student_can_view_own_complaint(self):
        self.client.force_login(self.student_a)
        response = self.client.get(reverse("complaints:detail", args=[self.complaint_a.complaint_code]))
        self.assertEqual(response.status_code, 200)

    def test_student_cannot_view_another_students_complaint(self):
        self.client.force_login(self.student_b)
        response = self.client.get(reverse("complaints:detail", args=[self.complaint_a.complaint_code]))
        self.assertEqual(response.status_code, 404)

    def test_student_director_get_denied(self):
        self.client.force_login(self.student_a)
        response = self.client.get(reverse("director_portal:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_student_director_post_denied(self):
        self.client.force_login(self.student_a)
        response = self.client.post(
            reverse("director_portal:complaint_detail", args=[self.complaint_a.pk]),
            data={"change_status": "1", "new_status": "UNDER_REVIEW"},
        )
        self.assertEqual(response.status_code, 403)
        self.complaint_a.refresh_from_db()
        self.assertEqual(self.complaint_a.status, "SUBMITTED")

    def test_student_cannot_reach_director_route_via_forged_url(self):
        # Direct URL access, not just hidden nav - CLAUDE.md rule #3.
        self.client.force_login(self.student_a)
        response = self.client.get(reverse("director_portal:complaint_list"))
        self.assertEqual(response.status_code, 403)

    def test_director_dashboard_allowed(self):
        self.client.force_login(self.director)
        response = self.client.get(reverse("director_portal:dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_director_can_view_any_complaint(self):
        self.client.force_login(self.director)
        response = self.client.get(reverse("director_portal:complaint_detail", args=[self.complaint_a.pk]))
        self.assertEqual(response.status_code, 200)

    def test_public_registration_cannot_grant_director_role(self):
        response = self.client.post(reverse("accounts:register"), data={
            "full_name": "Sneaky Student",
            "roll_number": "R999",
            "email": "sneaky@campus.edu",
            "mobile_number": "9999999999",
            "course": "CS",
            "branch": "CSE",
            "semester": 3,
            "password1": "verystrongpass1",
            "password2": "verystrongpass1",
            "role": "DIRECTOR",  # attempted injection - form has no such field
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="sneaky@campus.edu")
        self.assertEqual(user.role, Role.STUDENT)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_duplicate_email_registration_rejected(self):
        make_student("dup@campus.edu", "R500")
        response = self.client.post(reverse("accounts:register"), data={
            "full_name": "Dup", "roll_number": "R501", "email": "dup@campus.edu",
            "mobile_number": "9999999999", "course": "CS", "branch": "CSE", "semester": 1,
            "password1": "verystrongpass1", "password2": "verystrongpass1",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already exists")
