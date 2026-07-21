from datetime import datetime
import json

from django.conf import settings
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required

import logging

from common.djangoapps.edxmako.makoloader import MakoLoader
from common.djangoapps.edxmako.shortcuts import render_to_response
from custom_common.helpers import enroll_user_in_courses

from openedx.core.djangoapps.site_configuration import (
    helpers as configuration_helpers,
)
from openedx.core.djangoapps.xblock.runtime.shims import TemplateDoesNotExist

from c_ptc.helpers import _get_user
from c_ptc.models import UserPtcInfo

log = logging.getLogger(__name__)


def health(request):
    log.info("[PTC] Health endpoint called.")
    return JsonResponse(
        {
            "app": "c_ptc",
            "status": "ok",
        }
    )

@login_required    
def get_post_login_ptc(request):
    """
    Returns PTC popup configuration for the authenticated user.
    """
    user = _get_user(request)

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
        return None

    log.info("[PTC] c_ptc configuration=%s", c_ptc)

    types = c_ptc.get("type", [])
    enabled = c_ptc.get("enabled", True)
    
    if not enabled:
        log.info("[PTC] c_ptc is disabled.")
        return None

    if not types:
        log.warning("[PTC] No PTC types configured.")
        return None

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
        return None

    log.info(
        "[PTC] Pending PTC found. id=%s ptc_type=%s",
        user_ptc_info.id,
        user_ptc_info.ptc_type,
    )

    response = {
        "popup_url": request.build_absolute_uri(
            f"/c_ptc/fetch/{user_ptc_info.ptc_type}"
        ),
        "ptc_type": user_ptc_info.ptc_type,
        "mandatory": c_ptc.get("mandatory", True),
        "container_height": c_ptc.get("CONTAINER_HEIGHT", "70vh"),
        "container_width": c_ptc.get("CONTAINER_WIDTH", "40%"),
    }

    log.info("[PTC] Returning response=%s", response)

    return response

@login_required   
def fetch_ptc(request, ptc_type):
    log.info("[PTC] Fetch request received. ptc_type=%s", ptc_type)

    try:
        user = _get_user(request)

        if not user:
            log.warning("[PTC] Anonymous/invalid user.")
            return render_to_response(
                "c_ptc/show_message.html",
                {
                    "message": "User not found or not authenticated.",
                    "status": "error",
                },
            )

        log.info(
            "[PTC] User authenticated. user=%s ptc_type=%s",
            user.username,
            ptc_type,
        )

        user_ptc_info = UserPtcInfo.objects.filter(
            userid=user,
            ptc_type=ptc_type,
        ).first()

        if not user_ptc_info:
            log.warning(
                "[PTC] No PTC record found. user=%s ptc_type=%s",
                user.username,
                ptc_type,
            )

            return render_to_response(
                "c_ptc/show_message.html",
                {
                    "message": "No pending PTC found.",
                    "status": "error",
                },
            )

        if user_ptc_info.submitted_at:
            log.info(
                "[PTC] PTC already submitted. user=%s ptc_type=%s",
                user.username,
                ptc_type,
            )

            return render_to_response(
                "c_ptc/show_message.html",
                {
                    "message": "PTC already submitted.",
                    "status": "error",
                },
            )

        LMS_ROOT_URL = configuration_helpers.get_value(
            "LMS_ROOT_URL",
            settings.LMS_ROOT_URL,
        )

        try:
            user_ptc_info_metadata = json.loads(user_ptc_info.metadata or "{}")
        except (TypeError, ValueError):
            log.warning(
                "[PTC] Invalid metadata JSON for user=%s ptc_type=%s. Resetting metadata.",
                user.username,
                ptc_type,
            )
            user_ptc_info_metadata = {}

        data = {
            "name": f"{user.first_name} {user.last_name}",
            "email": user.email,
            "platform_url": LMS_ROOT_URL,
            "institution": user_ptc_info_metadata.get("institution"),
            "program_name": user_ptc_info_metadata.get("program_name"),
            "ptc_type": ptc_type,
        }

        log.info("[PTC] Updating metadata for user=%s", user.username)

        user_ptc_info_metadata.update(data)

        user_ptc_info.metadata = json.dumps(user_ptc_info_metadata)

        user_ptc_info.save(update_fields=["metadata"])

        log.info("[PTC] Metadata updated successfully.")

        template = f"c_ptc/{ptc_type}.html"

        log.info("[PTC] Looking for template=%s", template)

        if MakoLoader.get_template(template):
            log.info("[PTC] Rendering template=%s", template)

            return render_to_response(
                template,
                data,
            )

        log.error("[PTC] Template not found. template=%s", template)

        return render_to_response(
            "c_ptc/show_message.html",
            {
                "message": "PTC not found.",
                "status": "error",
            },
        )


    except Exception:
        log.exception(
            "[PTC] Unexpected error while fetching PTC. ptc_type=%s",
            ptc_type,
        )

        return render_to_response(
            "c_ptc/show_message.html",
            {
                "message": "Unexpected error occurred.",
                "status": "error",
            },
        )

@login_required   
def submit_ptc(request, ptc_type):
    log.info("[PTC] Submit request received. ptc_type=%s", ptc_type)

    response = {
        "error": False,
        "message": "PTC submitted successfully.",
        "data": {},
    }

    try:
        user = _get_user(request)

        if not user:
            log.warning("[PTC] Anonymous/invalid user.")

            response["error"] = True
            response["message"] = "User not found or not authenticated."
            return response

        log.info(
            "[PTC] Processing submission. user=%s ptc_type=%s",
            user.username,
            ptc_type,
        )

        user_ptc_info = UserPtcInfo.objects.filter(
            userid=user,
            ptc_type=ptc_type,
        ).first()

        if user_ptc_info is None:
            log.warning("[PTC] No pending PTC found.")

            response["error"] = True
            response["message"] = "No pending PTC found."
            return response

        if user_ptc_info.submitted_at:
            log.info("[PTC] PTC already submitted.")

            response["error"] = True
            response["message"] = "PTC already submitted."
            return response

        user_ptc_info.submitted_at = datetime.now()
        user_ptc_info.save(update_fields=["submitted_at"])

        log.info("[PTC] Submission timestamp saved.")

        courses = user_ptc_info.course_ids

        log.info("[PTC] Courses to enroll=%s", courses)

        if len(courses) == 0:
            response["message"] = (
                "PTC submitted successfully but no course enrolled."
            )

            log.info("[PTC] No courses configured.")

            return response

        success, already_enrolled, failed = enroll_user_in_courses(
            user,
            courses,
        )

        log.info(
            "[PTC] Enrollment completed. success=%s already=%s failed=%s",
            success,
            already_enrolled,
            failed,
        )

        if len(failed) == 0:
            response["message"] = (
                "PTC submitted successfully and enrolled in the following courses: "
                + ", ".join(success)
            )

        elif len(success) == 0 and len(already_enrolled) == 0:
            response["error"] = True
            response["message"] = "Failed to enroll any course."
            response["data"] = failed

        else:
            response["message"] = (
                "PTC submitted successfully but some courses failed to enroll: "
                + ", ".join(failed)
            )

        log.info("[PTC] Final response=%s", response)

    except Exception:
        log.exception(
            "[PTC] Unexpected error while submitting PTC. ptc_type=%s",
            ptc_type,
        )

        response["error"] = True
        response["message"] = "Internal server error."

    return response