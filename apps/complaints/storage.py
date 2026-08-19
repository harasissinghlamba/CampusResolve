"""
Phase 9: private evidence storage.

Production: private Supabase Storage bucket (SUPABASE_URL +
SUPABASE_SERVICE_ROLE_KEY, backend-only, never exposed to templates/JS).
Local dev / this sandbox (no Supabase network access): falls back to
Django's local FileSystemStorage under media/, so the app stays runnable
without live Supabase connectivity. Both paths share the same validation,
UUID-path generation, and ownership-checked retrieval flow.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage


class AttachmentValidationError(ValidationError):
    pass


def validate_attachment(uploaded_file) -> None:
    max_bytes = settings.MAX_ATTACHMENT_SIZE_MB * 1024 * 1024
    if uploaded_file.size > max_bytes:
        raise AttachmentValidationError(f"File exceeds the {settings.MAX_ATTACHMENT_SIZE_MB}MB limit.")

    content_type = getattr(uploaded_file, "content_type", "") or ""
    if content_type not in settings.ALLOWED_ATTACHMENT_TYPES:
        raise AttachmentValidationError(
            f"Unsupported file type '{content_type}'. Allowed: {', '.join(settings.ALLOWED_ATTACHMENT_TYPES)}."
        )


def _generate_storage_path(complaint, original_filename: str) -> str:
    # Never derive the storage path from the original filename - it is
    # untrusted input (CLAUDE.md rule #5).
    ext = ""
    if "." in original_filename:
        ext = "." + original_filename.rsplit(".", 1)[-1].lower()
        ext = "".join(c for c in ext if c.isalnum() or c == ".")[:10]
    return f"complaints/{complaint.pk}/{uuid.uuid4().hex}{ext}"


def _supabase_enabled() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY)


def save_attachment_file(complaint, uploaded_file):
    """Validate + persist the file bytes, returning the storage_path used."""
    validate_attachment(uploaded_file)
    storage_path = _generate_storage_path(complaint, uploaded_file.name)

    if _supabase_enabled():
        from supabase import create_client

        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
        bucket = client.storage.from_(settings.SUPABASE_STORAGE_BUCKET)
        bucket.upload(
            storage_path,
            uploaded_file.read(),
            {"content-type": uploaded_file.content_type},
        )
    else:
        default_storage.save(storage_path, uploaded_file)

    return storage_path


def get_authorized_file_url(attachment, expires_in: int = 300) -> str:
    """
    Caller MUST perform the ownership/role authorization check before calling
    this (see complaints.views.attachment_download) - this function assumes
    that check has already passed.
    """
    if _supabase_enabled():
        from supabase import create_client

        client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
        bucket = client.storage.from_(settings.SUPABASE_STORAGE_BUCKET)
        signed = bucket.create_signed_url(attachment.storage_path, expires_in)
        return signed.get("signedURL") or signed.get("signed_url")
    return default_storage.url(attachment.storage_path)
