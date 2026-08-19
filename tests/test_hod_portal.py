from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department, Role, User
from apps.complaints.models import ComplaintCategory
from apps.complaints.services import create_complaint, forward_complaint_to_department

from .test_authorization import make_director, make_student


def make_hod(email="hod.cse@campus.edu", department=Department.CSE):
    return User.objects.create_user(
        username=email, email=email, password="pass12345",
        full_name="HOD One", role=Role.HOD, department=department,
    )


class HodForwardingTests(TestCase):
    def setUp(self):
        self.category = ComplaintCategory.objects.create(name="Infrastructure", slug="infrastructure")
        self.student = make_student()
        self.director = make_director()
        self.hod_cse = make_hod("hod.cse@campus.edu", Department.CSE)
        self.hod_mech = make_hod("hod.mech@campus.edu", Department.MECHANICAL)
        self.complaint = create_complaint(
            student=self.student, category=self.category,
            subject="Lab AC not working", description="The CSE lab air conditioning has not worked in two weeks.",
        )

    def test_anonymous_to_hod_denied(self):
        response = self.client.get(reverse("hod_portal:dashboard"))
        self.assertEqual(response.status_code, 302)

    def test_student_to_hod_denied(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("hod_portal:dashboard"))
        self.assertEqual(response.status_code, 403)

    def test_director_can_forward_complaint(self):
        self.client.force_login(self.director)
        response = self.client.post(
            reverse("director_portal:complaint_detail", args=[self.complaint.pk]),
            data={"forward_complaint": "1", "department": Department.CSE},
        )
        self.assertEqual(response.status_code, 302)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.assigned_department, Department.CSE)
        self.assertIsNotNone(self.complaint.assigned_at)
        self.assertEqual(self.complaint.assigned_by, self.director)

    def test_hod_sees_only_own_department_queue(self):
        forward_complaint_to_department(complaint=self.complaint, department=Department.CSE, actor=self.director)

        self.client.force_login(self.hod_cse)
        response = self.client.get(reverse("hod_portal:dashboard"))
        self.assertContains(response, self.complaint.complaint_code)

        self.client.force_login(self.hod_mech)
        response = self.client.get(reverse("hod_portal:dashboard"))
        self.assertNotContains(response, self.complaint.complaint_code)

    def test_hod_cannot_open_complaint_not_forwarded_to_their_department(self):
        forward_complaint_to_department(complaint=self.complaint, department=Department.CSE, actor=self.director)
        self.client.force_login(self.hod_mech)
        response = self.client.get(reverse("hod_portal:complaint_detail", args=[self.complaint.pk]))
        self.assertEqual(response.status_code, 403)

    def test_hod_cannot_open_unforwarded_complaint(self):
        # Never forwarded at all - assigned_department is None, which must
        # never match any HOD's department.
        self.client.force_login(self.hod_cse)
        response = self.client.get(reverse("hod_portal:complaint_detail", args=[self.complaint.pk]))
        self.assertEqual(response.status_code, 403)

    def test_hod_detail_view_never_exposes_student_identity(self):
        forward_complaint_to_department(complaint=self.complaint, department=Department.CSE, actor=self.director)
        self.client.force_login(self.hod_cse)
        response = self.client.get(reverse("hod_portal:complaint_detail", args=[self.complaint.pk]))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn(self.student.full_name, content)
        self.assertNotIn(self.student.email, content)
        self.assertNotIn(self.student.roll_number, content)

    def test_hod_dashboard_never_exposes_student_identity(self):
        forward_complaint_to_department(complaint=self.complaint, department=Department.CSE, actor=self.director)
        self.client.force_login(self.hod_cse)
        response = self.client.get(reverse("hod_portal:dashboard"))
        content = response.content.decode()
        self.assertNotIn(self.student.full_name, content)
        self.assertNotIn(self.student.roll_number, content)

    def test_hod_can_update_status_and_remark_on_own_department_complaint(self):
        forward_complaint_to_department(complaint=self.complaint, department=Department.CSE, actor=self.director)
        self.client.force_login(self.hod_cse)

        response = self.client.post(
            reverse("hod_portal:complaint_detail", args=[self.complaint.pk]),
            data={"change_status": "1", "new_status": "UNDER_REVIEW", "remark": "Looking into it."},
        )
        self.assertEqual(response.status_code, 302)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, "UNDER_REVIEW")

        response = self.client.post(
            reverse("hod_portal:complaint_detail", args=[self.complaint.pk]),
            data={"save_remark": "1", "hod_remark": "AC technician scheduled for Friday."},
        )
        self.assertEqual(response.status_code, 302)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.hod_remark, "AC technician scheduled for Friday.")

    def test_student_sees_hod_remark_but_not_identity_of_hod_process(self):
        forward_complaint_to_department(complaint=self.complaint, department=Department.CSE, actor=self.director)
        self.complaint.hod_remark = "Technician scheduled for Friday."
        self.complaint.save()

        self.client.force_login(self.student)
        response = self.client.get(reverse("complaints:detail", args=[self.complaint.complaint_code]))
        self.assertContains(response, "Technician scheduled for Friday.")

    def test_public_registration_cannot_create_hod(self):
        # Same defense-in-depth as Director: role is never form input.
        response = self.client.post(reverse("accounts:register"), data={
            "full_name": "Sneaky", "roll_number": "R777", "email": "sneaky2@campus.edu",
            "mobile_number": "9999999999", "course": "CS", "branch": "CSE", "semester": 2,
            "password1": "verystrongpass1", "password2": "verystrongpass1",
            "role": "HOD", "department": "CSE",
        })
        user = User.objects.get(email="sneaky2@campus.edu")
        self.assertEqual(user.role, Role.STUDENT)
        self.assertIsNone(user.department)
