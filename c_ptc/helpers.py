
import logging
import requests
import json

from django.contrib.auth.models import User
from django.db.models import Q 

from c_ptc.models import UserPtcInfo

log = logging.getLogger("edx.student")

def _get_user(request, onlyNonStudent=False, anyUser = True):
    """Get User object from request email."""
    user = None
    try:
        request_user = request.GET.get("user")
        if request_user:
            user = User.objects.filter(
                Q(email=request_user) | Q(username=request_user)
            ).first()
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

def _create_user_ptc_info_record(user, ptc_type, courses, metadata={}):
    """Create PTC record for the user."""
    log.info(
        "[PTC] Creating PTC record for user_id=%s username=%s",
        user.id,
        user.username,
    )
    
    try:
        UserPtcInfo.objects.create(
            userid=user,
            ptc_type=ptc_type,
            course_ids=courses,
            metadata=json.dumps(metadata),
        )

        log.info(
            "[PTC] PTC record created for user_id=%s username=%s",
            user.id,
            user.username,
        )
        return True

    except Exception as e:
        log.error(
            "[PTC] Error creating PTC record for user_id=%s username=%s: %s",
            user.id,
            user.username,
            e,
        )
        return False