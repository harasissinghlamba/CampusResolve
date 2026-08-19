import io

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.complaints.models import Attachment, Complaint, ComplaintCategory, Status
from apps.complaints.services import change_complaint_status, create_complaint
from apps.complaints.storage import AttachmentValidationError, save_attachment_file, validate_attachment

from .test_authorization import make_director, make_student


class ComplaintCreationTests(TestCase):
    def setUp(self):
        self.category = ComplaintCategory.objects.create(name="Fees", slug="fees")
        self.student = make_student()

    def test_create_complaint_assigns_owner_server_side_and_scores_spam(self):
        complaint = create_complaint(
            student=self.student, category=self.category,
            subject="Fee receipt not generated", description="I paid fees but did not receive a receipt from the portal.",
        )
        self.assertEqual(complaint.student, self.student)
        self.assertEqual(complaint.status, Status.SUBMITTED)
        self.assertTrue(hasattr(complaint, "spam_analysis"))
        self.assertEqual(complaint.status_history.count(), 1)

    def test_complaint_list_view_is_ownership_scoped(self):
        other = make_student("other@campus.edu", "R901")
        create_complaint(student=self.student, category=self.category, subject="A", description="Normal complaint text here.")
        create_complaint(student=other, category=self.category, subject="B", description="Another normal complaint text.")

        self.client.force_login(self.student)
        response = self.client.get(reverse("complaints:list"))
        self.assertEqual(list(response.context["complaints"]), list(Complaint.objects.filter(student=self.student)))
        self.assertEqual(response.context["complaints"].count(), 1)


class StatusTransitionTests(TestCase):
    def setUp(self):
        self.category = ComplaintCategory.objects.create(name="IT", slug="it")
        self.student = make_student()
        self.director = make_director()
        self.complaint = create_complaint(
            student=self.student, category=self.category,
            subject="Portal down", description="The student portal has been down for two days now.",
        )

    def test_valid_transition_updates_status_and_history(self):
        change_complaint_status(complaint=self.complaint, new_status=Status.UNDER_REVIEW, actor=self.director)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Status.UNDER_REVIEW)
        self.assertEqual(self.complaint.status_history.count(), 2)

    def test_invalid_transition_rejected(self):
        # SUBMITTED -> RESOLVED is not an allowed transition.
        with self.assertRaises(ValidationError):
            change_complaint_status(complaint=self.complaint, new_status=Status.RESOLVED, actor=self.director)
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Status.SUBMITTED)

    def test_resolved_sets_timestamp(self):
        change_complaint_status(complaint=self.complaint, new_status=Status.UNDER_REVIEW, actor=self.director)
        change_complaint_status(complaint=self.complaint, new_status=Status.IN_PROGRESS, actor=self.director)
        change_complaint_status(complaint=self.complaint, new_status=Status.RESOLVED, actor=self.director)
        self.complaint.refresh_from_db()
        self.assertIsNotNone(self.complaint.resolved_at)

    def test_public_vs_internal_remark_isolation(self):
        self.complaint.director_public_remark = "We are looking into it."
        self.complaint.director_internal_note = "Escalate to IT team lead - suspect server issue."
        self.complaint.save()

        self.client.force_login(self.student)
        response = self.client.get(reverse("complaints:detail", args=[self.complaint.complaint_code]))
        self.assertContains(response, "We are looking into it.")
        self.assertNotContains(response, "Escalate to IT team lead")


class AttachmentTests(TestCase):
    def setUp(self):
        self.category = ComplaintCategory.objects.create(name="Library", slug="library")
        self.student = make_student()
        self.other_student = make_student("other2@campus.edu", "R902")
        self.complaint = create_complaint(
            student=self.student, category=self.category,
            subject="Book fine dispute", description="I was charged a fine for a book I returned on time.",
        )

    def test_oversized_file_rejected(self):
        big_file = SimpleUploadedFile("evidence.pdf", b"x" * (9 * 1024 * 1024), content_type="application/pdf")
        with self.settings(MAX_ATTACHMENT_SIZE_MB=8):
            with self.assertRaises(AttachmentValidationError):
                validate_attachment(big_file)

    def test_disallowed_type_rejected(self):
        exe_file = SimpleUploadedFile("evidence.exe", b"binary", content_type="application/x-msdownload")
        with self.assertRaises(AttachmentValidationError):
            validate_attachment(exe_file)

    def test_valid_attachment_saved_with_uuid_path_not_original_name(self):
        pdf = SimpleUploadedFile("my secret evidence.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
        storage_path = save_attachment_file(self.complaint, pdf)
        self.assertNotIn("my secret evidence", storage_path)
        self.assertTrue(storage_path.endswith(".pdf"))

    def test_unauthorized_attachment_access_denied(self):
        attachment = Attachment.objects.create(
            complaint=self.complaint, storage_path="complaints/1/fake.pdf",
            original_filename="evidence.pdf", content_type="application/pdf", size_bytes=10,
        )
        self.client.force_login(self.other_student)
        response = self.client.get(reverse("complaints:attachment_download", args=[attachment.id]))
        self.assertEqual(response.status_code, 403)

    def test_owner_can_access_own_attachment(self):
        attachment = Attachment.objects.create(
            complaint=self.complaint, storage_path="complaints/1/fake.pdf",
            original_filename="evidence.pdf", content_type="application/pdf", size_bytes=10,
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse("complaints:attachment_download", args=[attachment.id]))
        self.assertEqual(response.status_code, 302)  # redirected to the (local) file URL
