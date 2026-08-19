"""
HOD authorization. Two layers, both enforced server-side:
  1. role_required: the user must be authenticated with role=HOD.
  2. Per-object: an HOD may only act on complaints where
     complaint.assigned_department == request.user.department. An HOD for
     CSE can never see a complaint forwarded to Mechanical, even via a
     guessed URL.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def hod_required(view_func):
    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not (request.user.is_authenticated and request.user.is_hod):
            raise PermissionDenied("HOD access required.")
        if not request.user.department:
            raise PermissionDenied("This HOD account has no department assigned.")
        return view_func(request, *args, **kwargs)

    return _wrapped
