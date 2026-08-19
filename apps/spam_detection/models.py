from django.db import models

from apps.complaints.models import Complaint, SpamClassification


class SpamAnalysis(models.Model):
    """
    One row per scored complaint. The score/classification is decision
    support for the Director - it never triggers automatic deletion or an
    automatic status change (CLAUDE.md rule #9).
    """

    complaint = models.OneToOneField(Complaint, on_delete=models.CASCADE, related_name="spam_analysis")

    duplicate_score = models.PositiveSmallIntegerField(default=0)
    frequency_score = models.PositiveSmallIntegerField(default=0)
    low_information_score = models.PositiveSmallIntegerField(default=0)
    repetition_score = models.PositiveSmallIntegerField(default=0)
    prior_spam_score = models.PositiveSmallIntegerField(default=0)
    similarity_score = models.PositiveSmallIntegerField(default=0)  # Phase 10 (TF-IDF), 0 until enabled

    final_score = models.PositiveSmallIntegerField(default=0)
    classification = models.CharField(
        max_length=12, choices=SpamClassification.choices, default=SpamClassification.NORMAL
    )
    reasons = models.JSONField(default=list, blank=True)  # list[str], human-readable
    rules_version = models.CharField(max_length=20, default="v1")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"SpamAnalysis({self.complaint.complaint_code}={self.final_score})"
