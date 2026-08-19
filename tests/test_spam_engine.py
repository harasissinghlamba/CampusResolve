from django.test import TestCase

from apps.complaints.models import Complaint, ComplaintCategory, SpamClassification
from apps.complaints.services import create_complaint
from apps.spam_detection.engine import analyze_complaint

from .test_authorization import make_student


class SpamEngineTests(TestCase):
    def setUp(self):
        self.category = ComplaintCategory.objects.create(name="Transport", slug="transport")
        self.student = make_student()

    def test_normal_complaint_stays_low(self):
        result = analyze_complaint(
            student=self.student,
            subject="Bus route 12 consistently late",
            description=(
                "The route 12 shuttle has arrived over twenty minutes late every day this week, "
                "making several of us miss our first lecture. Could the schedule be reviewed?"
            ),
            use_tfidf=False,
        )
        self.assertLessEqual(result.final_score, 29)
        self.assertEqual(result.classification, SpamClassification.NORMAL)

    def test_low_information_text_flagged(self):
        result = analyze_complaint(student=self.student, subject="bad", description="fix it", use_tfidf=False)
        self.assertGreater(result.final_score, 0)
        self.assertIn("short", " ".join(result.reasons).lower())

    def test_excessive_repetition_flagged(self):
        result = analyze_complaint(
            student=self.student, subject="spam spam spam",
            description="aaaaaaaaaaaaaaaaaaaa spam spam spam spam spam spam spam",
            use_tfidf=False,
        )
        self.assertGreaterEqual(result.repetition_score, 1)

    def test_exact_duplicate_from_same_student_flagged(self):
        create_complaint(
            student=self.student, category=self.category, subject="Wifi outage in block C",
            description="The wifi in hostel block C has been down since Monday morning and nobody has responded.",
        )
        result = analyze_complaint(
            student=self.student, subject="Wifi outage in block C",
            description="The wifi in hostel block C has been down since Monday morning and nobody has responded.",
            use_tfidf=False,
        )
        self.assertGreaterEqual(result.duplicate_score, 30)
        self.assertIn(result.classification, [SpamClassification.REVIEW, SpamClassification.SUSPICIOUS])

    def test_burst_frequency_flagged(self):
        for i in range(4):
            create_complaint(
                student=self.student, category=self.category, subject=f"Issue number {i}",
                description=f"This is a distinct legitimate complaint about a campus issue, instance {i}.",
            )
        result = analyze_complaint(
            student=self.student, subject="One more issue",
            description="Yet another distinct legitimate complaint about a different campus issue entirely.",
            use_tfidf=False,
        )
        self.assertGreater(result.frequency_score, 0)

    def test_spam_analysis_never_deletes_or_forces_status(self):
        complaint = create_complaint(
            student=self.student, category=self.category, subject="x", description="y",
        )
        # Even a low-information complaint that scores high stays SUBMITTED
        # and stored - scoring is decision support only (CLAUDE.md rule #9).
        self.assertTrue(Complaint.objects.filter(pk=complaint.pk).exists())
        self.assertEqual(complaint.status, "SUBMITTED")
