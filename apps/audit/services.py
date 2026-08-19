"""
Thin, deliberately boring audit-logging service. Views/services call
log_action() instead of writing to AuditLog directly, so the "never log
PII/secrets" rule lives in exactly one place.
"""
from .models import AuditLog

_FORBIDDEN_KEYS = {"password", "otp", "db_password", "service_key", "description", "text"}


def log_action(*, actor, action: str, target: str = "", metadata: dict | None = None):
    metadata = metadata or {}
    safe_metadata = {k: v for k, v in metadata.items() if k.lower() not in _FORBIDDEN_KEYS}
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", True) else None,
        action=action,
        target=target,
        metadata=safe_metadata,
    )
