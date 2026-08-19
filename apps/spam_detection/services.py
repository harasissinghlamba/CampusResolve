from django.db import transaction

from .engine import analyze_complaint
from .models import SpamAnalysis


@transaction.atomic
def run_and_save_spam_analysis(complaint, use_tfidf: bool = True) -> SpamAnalysis:
    """
    Score a complaint and persist SpamAnalysis + denormalized summary fields
    on Complaint, inside one transaction. Called from the complaint-creation
    service so scoring never leaves a complaint half-saved.
    """
    result = analyze_complaint(
        student=complaint.student,
        subject=complaint.subject,
        description=complaint.description,
        exclude_pk=complaint.pk,
        use_tfidf=use_tfidf,
    )

    analysis, _ = SpamAnalysis.objects.update_or_create(
        complaint=complaint,
        defaults=dict(
            duplicate_score=result.duplicate_score,
            frequency_score=result.frequency_score,
            low_information_score=result.low_information_score,
            repetition_score=result.repetition_score,
            prior_spam_score=result.prior_spam_score,
            similarity_score=result.similarity_score,
            final_score=result.final_score,
            classification=result.classification,
            reasons=result.reasons,
        ),
    )

    complaint.spam_score = result.final_score
    complaint.spam_classification = result.classification
    complaint.save(update_fields=["spam_score", "spam_classification"])

    return analysis
