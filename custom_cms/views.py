import json
import logging

from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.http import JsonResponse
from django.conf import settings

from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated

from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from edx_rest_framework_extensions.permissions import NotJwtRestrictedApplication

from openedx.core.djangoapps.enrollments.api import add_enrollment
from openedx.core.djangoapps.enrollments.errors import CourseEnrollmentExistsError
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers

from custom_common.helpers import (
    create_user,
    deactivate_enrollments,
    generate_random_password,
    generate_username,
    send_enrollment_email,
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
    first_name = payload.get("firstname", "")
    last_name = payload.get("lastname", "")
    username = payload.get("username")
    password = payload.get("password")

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

    courses = get_unique_courses(payload.get("courses", []), course_config.get("courses", []))
    log.info("Courses prepared | count=%s", len(courses), extra={"courses": courses})

    user = User.objects.filter(email=email).first()
    generated_password = False

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
            log.info("Generated username | username=%s", username)

        if not password:
            password = generate_random_password()
            generated_password = True
            log.info("Generated temporary password | email=%s | password=%s", email, password)

        user = create_user(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            password=password,
        )

    success = []
    failed = []
    already_enrolled = []

    is_unenroll = enroll == "0"

    for course in courses:
        try:
            log.info("Processing course | user_id=%s | username=%s | course=%s", user.id, username, course)

            if is_unenroll:
                log.info("Unenrolling user | user_id=%s | username=%s | course=%s", user.id, username, course)
                deactivate_enrollments(user, course)
                success.append(course)
                continue

            add_enrollment(user.username,course)
            success.append(course)
            log.info("Course enrollment completed | user_id=%s course=%s", user.id, course)

        except CourseEnrollmentExistsError:
            log.info("User already enrolled | user_id=%s course=%s", user.id, course)
            already_enrolled.append(course)

        except Exception as exc:
            log.exception("Course enrollment failed | user_id=%s course=%s", user.id, course)
            failed.append({"course": course, "error": str(exc)})

    mail_details = course_config.get("mail_details", {})

    if (
        mail_details.get("enable")
        and mail_details.get("subject")
        and mail_details.get("body_template_name")
    ):
        try:
            send_enrollment_email(user, password, mail_details)

        except Exception as exc:
            log.exception("Enrollment email failed | user_id=%s", user.id, exc_info=True)
            recipient_list = mail_details.get("support_emails", [])
            if not recipient_list:
                recipient_list = [settings.CONTACT_EMAIL]
            from_email = settings.CONTACT_EMAIL if settings.CONTACT_EMAIL not in recipient_list else "no-reply@alv.talentsprint.com"
            send_mail(
                subject="Error in sending enrollment email",
                message=(
                    f"Unable to send enrollment email "
                    f"for user {user.email}: {exc}"
                ),
                from_email=from_email,
                recipient_list=recipient_list,
                fail_silently=True,
            )

    else:
        log.info("Enrollment email disabled | config_key=%s", config_key)

    response = {
        "error": bool(failed),
        "message": "Processed enrollment request",
        "data": {
            "success": success,
            "failed": failed,
            "already_enrolled": already_enrolled,
            "generated_password": (
                password
                if generated_password and not is_unenroll and not bool(failed)
                else None
            ),
        },
    }

    log.info("Enrollment request completed | user_id=%s success=%s failed=%s", user.id, len(success), len(failed))

    return JsonResponse(response, status=200)