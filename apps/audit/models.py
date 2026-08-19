from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """
    Security-relevant administrative action log. Never store passwords,
    OTPs, DB credentials, service keys, or complaint text/PII in `metadata`.
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=100)
    target = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["action", "created_at"]),
            models.Index(fields=["actor", "created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        who = self.actor.email if self.actor else "system"
        return f"{self.created_at:%Y-%m-%d %H:%M} {who} {self.action} {self.target}"
