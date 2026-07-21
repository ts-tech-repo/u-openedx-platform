import logging

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from openedx.core.djangoapps.site_configuration import (
    helpers as configuration_helpers,
)

from c_ptc.models import UserPtcInfo

log = logging.getLogger(__name__)


@receiver(user_logged_in)
def user_login(sender, request, user, **kwargs):
    """
    Triggered whenever a user successfully logs in.
    Checks whether a PTC popup should be shown.
    """

    log.info("Login detected for user=%s (%s)", user.username, user.id)

    post_login_features = configuration_helpers.get_value(
        "POST_LOGIN_FEATURES",
        {},
    )

    c_ptc = post_login_features.get("c_ptc")

    if not c_ptc:
        log.debug("POST_LOGIN_FEATURES.c_ptc is not configured.")
        return

    types = c_ptc.get("type", [])

    if not types:
        log.debug("No PTC types configured.")
        return

    log.debug("Configured PTC types: %s", types)

    user_ptc_info = (
        UserPtcInfo.objects
        .filter(
            userid=user,
            ptc_type__in=types,
        )
        .first()
    )

    if not user_ptc_info:
        log.info(
            "No pending PTC record found for user=%s",
            user.username,
        )
        return

    if user_ptc_info.submitted_at:
        log.info(
            "PTC already submitted for user=%s, ptc_type=%s",
            user.username,
            user_ptc_info.ptc_type,
        )
        return

    popup_url = request.build_absolute_uri(
        f"/c_ptc/fetch/{user_ptc_info.ptc_type}"
    )

    response = {
        "error": False,
        "message": "",
        "data": {
            "popup_url": popup_url,
            "mandatory": c_ptc.get("mandatory", True),
            "container_height": c_ptc.get("CONTAINER_HEIGHT", "70vh"),
            "container_width": c_ptc.get("CONTAINER_WIDTH", "40%"),
        },
    }

    log.info(
        "Pending PTC found for user=%s, ptc_type=%s",
        user.username,
        user_ptc_info.ptc_type,
    )

    log.info("PTC response: %s", response)

    # NOTE:
    # Returning a value from a Django signal receiver has NO effect.
    # If the frontend needs this response, store it in the session,
    # cache, or expose it via an API that the frontend calls after login.
    return