
import logging
import requests
import json

from django.contrib.auth.models import User
from django.db.models import Q 

from openedx.core.djangoapps.site_configuration import (
    helpers as configuration_helpers,
)

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
    
def _get_post_login_ptc_data(request, user=None):
    """
    Returns PTC popup configuration for the authenticated user.
    """
    response = {
        "error": False,
        "message": "PTC configuration fetched successfully.",
        "data": {},
    }
    user = _get_user(request) if user is None else user

    log.info(
        "[PTC] Checking post-login PTC. user_id=%s username=%s",
        user.id,
        user.username,
    )

    post_login_features = configuration_helpers.get_value(
        "POST_LOGIN_FEATURES",
        {},
    )

    log.info("[PTC] POST_LOGIN_FEATURES=%s", post_login_features)

    c_ptc = post_login_features.get("c_ptc")

    if not c_ptc:
        log.info("[PTC] c_ptc configuration not found.")
        response["error"] = True
        response["message"] = "c_ptc configuration not found."
        return response

    log.info("[PTC] c_ptc configuration=%s", c_ptc)

    types = c_ptc.get("type", [])
    enabled = c_ptc.get("enabled", True)
    
    if not enabled:
        log.info("[PTC] c_ptc is disabled.")
        response["error"] = True
        response["message"] = "c_ptc is disabled."
        return response

    if not types:
        log.warning("[PTC] No PTC types configured.")
        response["error"] = True
        response["message"] = "No PTC types configured."
        return response

    log.info("[PTC] Configured PTC types=%s", types)
    
    user_ptc_info = None
    
    for ptc_type in types:
        user_ptc_info = UserPtcInfo.objects.filter(
            userid=user,
            ptc_type=ptc_type,
            submitted_at__isnull=True,
        ).first()

        if user_ptc_info:
            break

    if not user_ptc_info:
        log.info(
            "[PTC] No pending PTC found. user=%s",
            user.username,
        )

        response["message"] = "No pending PTC found."
        return response

    log.info(
        "[PTC] Pending PTC found. id=%s ptc_type=%s",
        user_ptc_info.id,
        user_ptc_info.ptc_type,
    )

    data = {
        "url": request.build_absolute_uri(
            f"/ptc/fetch/{user_ptc_info.ptc_type}"
        ).replace("http://", "https://", 1),
        "type": user_ptc_info.ptc_type,
        "mandatory": c_ptc.get("mandatory", True),
        "container_height": c_ptc.get("CONTAINER_HEIGHT", "80vh"),
        "container_width": c_ptc.get("CONTAINER_WIDTH", "90%"),
    }

    log.info("[PTC] Returning response=%s", data)
    response["data"] = data

    return response
