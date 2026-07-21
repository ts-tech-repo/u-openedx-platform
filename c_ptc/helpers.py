
import logging
import requests

from django.contrib.auth.models import User 

log = logging.getLogger("edx.student")

def _get_user(request, onlyNonStudent=False, anyUser = True):
    """Get User object from request email."""
    user = None
    try:
        email = request.GET.get("email", None)
        if email:
            user = User.objects.filter(email=email).first()
        else:
            user = request.user
    except Exception:
        log.exception("Failed to get user from request")

    if user and user.is_authenticated and not anyUser:
        if onlyNonStudent and (request.user.is_staff or request.user.is_superuser):
            return user
        else:
            log.warning("User %s is not staff/superuser, access denied", user.username)
            return None
    return user