"""
Phase 7: Director authorization.

Every /director/ route must use director_required (function views) or
DirectorRequiredMixin (class-based views). Both reject:
  - anonymous users -> redirect to login
  - authenticated non-Director/non-Admin users -> HTTP 403

Hiding nav links for students is UI only and is never sufficient on its own
(ARCHITECTURE.md / CLAUDE.md rule #3). This check is independent per-route,
not inherited implicitly from URL namespace.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def _is_director_or_admin(user) -> bool:
    return user.is_authenticated and (user.is_director or user.is_admin_role)


def director_required(view_func):
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not _is_director_or_admin(request.user):
            raise PermissionDenied("Director access required.")
        return view_func(request, *args, **kwargs)

    return _wrapped


class DirectorRequiredMixin:
    """Class-based-view equivalent of director_required."""

    def dispatch(self, request, *args, **kwargs):
        from django.contrib.auth.views import redirect_to_login

        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not _is_director_or_admin(request.user):
            raise PermissionDenied("Director access required.")
        return super().dispatch(request, *args, **kwargs)
