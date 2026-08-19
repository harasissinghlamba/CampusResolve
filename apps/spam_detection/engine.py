"""
Spam scoring engine.

Design goals (README/CLAUDE.md/ARCHITECTURE.md):
  * Pure-Python, testable in isolation from views/HTTP.
  * Returns an explainable score: component scores + human-readable reasons.
  * Never deletes or auto-suppresses a complaint; only informs the Director.
  * Treats cross-student similarity cautiously - many students may
    legitimately report the same real incident, so similarity is only ever
    scored *within the same student's own history* here.

Bands (README): 0-29 NORMAL, 30-59 REVIEW, 60-100 SUSPICIOUS.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

# Phase 6 suggested weights (CLAUDE.md). Total without similarity = 100;
# final score is always clamped to [0, 100].
WEIGHT_DUPLICATE = 30
WEIGHT_FREQUENCY = 25
WEIGHT_LOW_INFO = 10
WEIGHT_REPETITION = 15
WEIGHT_PRIOR_SPAM = 10
WEIGHT_OTHER = 10
WEIGHT_SIMILARITY = 20  # Phase 10, TF-IDF; only applied if enabled

NORMAL_MAX = 29
REVIEW_MAX = 59


@dataclass
class SpamResult:
    duplicate_score: int = 0
    frequency_score: int = 0
    low_information_score: int = 0
    repetition_score: int = 0
    prior_spam_score: int = 0
    similarity_score: int = 0
    other_score: int = 0
    reasons: list[str] = field(default_factory=list)

    @property
    def final_score(self) -> int:
        total = (
            self.duplicate_score
            + self.frequency_score
            + self.low_information_score
            + self.repetition_score
            + self.prior_spam_score
            + self.similarity_score
            + self.other_score
        )
        return max(0, min(100, total))

    @property
    def classification(self) -> str:
        score = self.final_score
        if score <= NORMAL_MAX:
            return "NORMAL"
        if score <= REVIEW_MAX:
            return "REVIEW"
        return "SUSPICIOUS"


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _similarity_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def score_duplicate(student, subject: str, description: str, exclude_pk=None) -> tuple[int, str | None]:
    """Same-user exact/near-duplicate detection against recent complaints."""
    from apps.complaints.models import Complaint  # local import avoids app-loading cycles

    normalized = normalize_text(f"{subject} {description}")
    recent = Complaint.objects.filter(student=student).order_by("-created_at")[:20]
    for other in recent:
        if exclude_pk and other.pk == exclude_pk:
            continue
        other_normalized = normalize_text(f"{other.subject} {other.description}")
        if not other_normalized:
            continue
        ratio = _similarity_ratio(normalized, other_normalized)
        if ratio >= 0.95:
            return WEIGHT_DUPLICATE, f"Near-identical to your earlier complaint {other.complaint_code}"
        if ratio >= 0.8:
            return int(WEIGHT_DUPLICATE * 0.6), f"Very similar to your earlier complaint {other.complaint_code}"
    return 0, None


def score_frequency(student) -> tuple[int, str | None]:
    """Burst-frequency detection using configurable per-hour/per-day limits."""
    from apps.complaints.models import Complaint

    now = timezone.now()
    per_hour_limit = getattr(settings, "SPAM_SUBMISSIONS_PER_HOUR", 3)
    per_day_limit = getattr(settings, "SPAM_SUBMISSIONS_PER_DAY", 8)

    last_hour = Complaint.objects.filter(student=student, created_at__gte=now - timedelta(hours=1)).count()
    last_day = Complaint.objects.filter(student=student, created_at__gte=now - timedelta(days=1)).count()

    if last_hour >= per_hour_limit:
        return WEIGHT_FREQUENCY, f"{last_hour} complaints submitted in the last hour"
    if last_day >= per_day_limit:
        return int(WEIGHT_FREQUENCY * 0.6), f"{last_day} complaints submitted in the last 24 hours"
    return 0, None


def score_low_information(description: str) -> tuple[int, str | None]:
    text = normalize_text(description)
    word_count = len(text.split())
    if word_count == 0:
        return WEIGHT_LOW_INFO, "Description is empty"
    if word_count < 5:
        return WEIGHT_LOW_INFO, "Description is extremely short / low-information"
    if word_count < 10:
        return int(WEIGHT_LOW_INFO * 0.5), "Description is quite short"
    return 0, None


def score_repetition(description: str) -> tuple[int, str | None]:
    text = normalize_text(description)
    if not text:
        return 0, None

    # Excessive repeated characters, e.g. "aaaaaaaaa" or "!!!!!!!!!"
    if re.search(r"(.)\1{6,}", text):
        return WEIGHT_REPETITION, "Excessive repeated characters detected"

    words = text.split()
    if len(words) >= 6:
        distinct_ratio = len(set(words)) / len(words)
        if distinct_ratio < 0.3:
            return WEIGHT_REPETITION, "Text is highly repetitive (low word variety)"
        if distinct_ratio < 0.5:
            return int(WEIGHT_REPETITION * 0.6), "Text shows noticeable word repetition"
    return 0, None


def score_prior_spam(student) -> tuple[int, str | None]:
    from apps.complaints.models import Complaint, Status

    count = Complaint.objects.filter(student=student, status=Status.SPAM).count()
    if count >= 3:
        return WEIGHT_PRIOR_SPAM, f"Student has {count} prior complaints marked as spam"
    if count >= 1:
        return int(WEIGHT_PRIOR_SPAM * 0.5), f"Student has {count} prior complaint(s) marked as spam"
    return 0, None


def score_similarity_tfidf(student, subject: str, description: str, exclude_pk=None) -> tuple[int, str | None]:
    """
    Phase 10: TF-IDF + cosine similarity against the student's own recent
    complaints. Deliberately scoped to the SAME student only - comparing
    across students is not done here, since many students legitimately
    reporting the same real incident must never be penalized.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    from apps.complaints.models import Complaint

    text = normalize_text(f"{subject} {description}")
    if not text:
        return 0, None

    recent = list(
        Complaint.objects.filter(student=student)
        .exclude(pk=exclude_pk)
        .order_by("-created_at")[:15]
    )
    corpus_texts = [normalize_text(f"{c.subject} {c.description}") for c in recent]
    corpus_texts = [t for t in corpus_texts if t]
    if not corpus_texts:
        return 0, None

    try:
        vectorizer = TfidfVectorizer(stop_words="english")
        matrix = vectorizer.fit_transform([text] + corpus_texts)
    except ValueError:
        # Empty vocabulary (e.g. all stopwords) - nothing meaningful to compare.
        return 0, None

    similarities = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    max_sim = float(similarities.max()) if len(similarities) else 0.0

    if max_sim >= 0.9:
        return WEIGHT_SIMILARITY, "Highly similar (TF-IDF) to one of your recent complaints"
    if max_sim >= 0.7:
        return int(WEIGHT_SIMILARITY * 0.5), "Moderately similar (TF-IDF) to one of your recent complaints"
    return 0, None


def analyze_complaint(student, subject: str, description: str, exclude_pk=None, use_tfidf: bool = True) -> SpamResult:
    """Run all signals and return an explainable SpamResult."""
    result = SpamResult()

    result.duplicate_score, reason = score_duplicate(student, subject, description, exclude_pk)
    if reason:
        result.reasons.append(reason)

    result.frequency_score, reason = score_frequency(student)
    if reason:
        result.reasons.append(reason)

    result.low_information_score, reason = score_low_information(description)
    if reason:
        result.reasons.append(reason)

    result.repetition_score, reason = score_repetition(description)
    if reason:
        result.reasons.append(reason)

    result.prior_spam_score, reason = score_prior_spam(student)
    if reason:
        result.reasons.append(reason)

    if use_tfidf:
        try:
            result.similarity_score, reason = score_similarity_tfidf(student, subject, description, exclude_pk)
            if reason:
                result.reasons.append(reason)
        except Exception:
            # Similarity is an enhancement, not a hard requirement - never let
            # it break complaint submission.
            result.similarity_score = 0

    if not result.reasons:
        result.reasons.append("No suspicious signals detected")

    return result
