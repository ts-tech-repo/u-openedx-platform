import json
import logging

from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.http import JsonResponse
from django.conf import settings

from c_ptc.helpers import _create_user_ptc_info_record
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated

from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from edx_rest_framework_extensions.permissions import NotJwtRestrictedApplication

from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers

from custom_common.utils.deteministic_safe_aes import encrypt
from custom_common.helpers import (
    create_user,
    generate_random_password,
    generate_username,
    send_enrollment_email,
    enroll_user_in_courses,
)


log = logging.getLogger("__name__")


def health(request):
    """
    Health check endpoint.
    """

    return JsonResponse(
        {
            "app": "custom_cms",
            "status": "ok",
        }
    )


def get_unique_courses(courses, configured_courses):
    """
    Merge courses without duplicate entries
    while preserving order.
    """

    return list(dict.fromkeys(courses + configured_courses))

@api_view(["POST"])
@authentication_classes([JwtAuthentication])
@permission_classes(
    [
        IsAuthenticated,
        NotJwtRestrictedApplication,
    ]
)
def extras_course_enroll_user(request, enroll="1"):
    """
    Create user and enroll user into courses.
    """

    log.info(
        "Enrollment request received | requester=%s",
        request.user.username,
    )

    try:
        payload = json.loads(request.body)

    except json.JSONDecodeError:
        log.exception("Invalid JSON payload")

        return JsonResponse(
            {
                "error": True,
                "message": "Invalid JSON payload",
            },
            status=400,
        )
        
    log.info("Payload: %s", payload)

    email = payload.get("email")
    first_name = payload.get("firstname", "").strip()
    last_name = payload.get("lastname", "").strip()
    username = payload.get("username")
    password = payload.get("password")
    enable_ptc = False

    if enroll not in ["0", "1"]:
        log.warning("Invalid enroll value | value=%s", enroll)

        return JsonResponse(
            {
                "error": True,
                "message": "Invalid enroll value. Allowed values are 0 or 1.",
            },
            status=400,
        )

    if not email:
        return JsonResponse({"error": True, "message": "email is mandatory"}, status=400)

    config_key = payload.get("config_key")

    if not config_key:
        return JsonResponse({"error": True, "message": "config_key is mandatory"}, status=400)

    try:
        enrollment_config = configuration_helpers.get_value("COURSE_ENROLLMENT_CONFIG",{})
    except Exception as e:
        log.exception("Unable to load course enrollment configuration | error=%s", e)

        return JsonResponse(
            {
                "error": True,
                "message": "Unable to load configuration",
            },
            status=500,
        )
    log.info("Enrollment configuration loaded: %s", enrollment_config)
    course_config = enrollment_config.get(config_key, {})

    if not course_config:
        log.warning("Invalid config key | config_key=%s", config_key)

        return JsonResponse(
            {
                "error": True,
                "message": "Invalid config_key",
            },
            status=400,
        )
    post_login_popup = course_config.get("post_login_popup", {})
    log.info("Post login popup: %s", post_login_popup)
    
    ptc_type = post_login_popup.get("ptc_type", "") if post_login_popup else []
    
    if ptc_type:
        enable_ptc = post_login_popup.get("enable_ptc", True)
    
    institution = post_login_popup.get("institution", "-")
    program_name = post_login_popup.get("program_name", "-")
    metadata = {
        "institution": institution,
        "program_name": program_name
    }
    log.info("PTC Metadata: %s", metadata)

    user = User.objects.filter(email=email).first()
    generated_password = False
    generated_username = False

    if user:
        log.info("Existing user found | user_id=%s", user.id)

    else:
        if not first_name:
            return JsonResponse(
                {
                    "error": True,
                    "message": "first_name is mandatory",
                },
                status=400,
            )

        if not username:
            username = generate_username(email)
            generated_username = True
            log.info("Generated username | username=%s", username)

        if not password:
            password = generate_random_password()
            generated_password = True
            log.info("Generated temporary password | email=%s | encrypted_password=%s", email, encrypt(password))

        user = create_user(
            username=username,
            email=email,
            first_name=last_name,
            last_name=first_name,
            password=password,
        )
        
    success = []
    already_enrolled = []
    failed = []

    is_unenroll = enroll == "0"
    courses = get_unique_courses(payload.get("courses", []), course_config.get("courses", []))
    log.info("Courses prepared | count=%s", len(courses), extra={"courses": courses})
    
    if not enable_ptc:    
        success, already_enrolled, failed = enroll_user_in_courses(user, courses, is_unenroll)
    else:
        log.info("Creating PTC Record for user: %s | ptc_type=%s | courses=%s", user.username, ptc_type, courses)
        ptc_record = _create_user_ptc_info_record(user, ptc_type, courses, metadata)
        if ptc_record:
            log.info("PTC Record created")

    mail_details = course_config.get("mail_details", {})

    if (
    mail_details.get("enable")
    and mail_details.get("subject")
    and mail_details.get("body_template_name")
):
        email_sent = send_enrollment_email(
            user=user,
            password=password,
            mail_details=mail_details,
        )

        if not email_sent:
            try:
                recipient_list = (
                    mail_details.get("support_emails")
                    or [settings.CONTACT_EMAIL]
                )

                from_email = (
                    settings.CONTACT_EMAIL
                    if settings.CONTACT_EMAIL not in recipient_list
                    else "no-reply@alv.talentsprint.com"
                )

                send_mail(
                    subject="Enrollment email delivery failed",
                    message=(
                        f"Enrollment completed successfully.\n\n"
                        f"User: {user.email}\n"
                        f"User ID: {user.id}\n\n"
                        f"Email notification could not be delivered."
                    ),
                    from_email=from_email,
                    recipient_list=recipient_list,
                    fail_silently=True,
                )

            except Exception as e:
                log.exception("Failed to send email | error=%s", e)

    else:
        log.info("Enrollment email disabled | config_key=%s", config_key)
        
    data = {}

    if failed:
        data["error_details"] = failed
        
    elif not is_unenroll:
        data["user_details"] = {}
        if generated_username:
            data["user_details"]["generated_username"] = username
        if generated_password:
            data["user_details"]["generated_password"] = password
        

    response = {
        "error": bool(failed),
        "message": "success" if not failed else "failed",
        "data": data
    }

    log.info("Enrollment request completed | user_id=%s success=%s failed=%s", user.id, len(success), len(failed))

    return JsonResponse(response, status=200)
