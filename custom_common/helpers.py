import logging
import re
import secrets
import string

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives, send_mail
import requests

from common.djangoapps.edxmako.shortcuts import render_to_string
from common.djangoapps.student.helpers import do_create_account
from common.djangoapps.util.password_policy_validators import validate_password
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers
from openedx.core.djangoapps.user_authn.views.registration_form import AccountCreationForm

from django.conf import settings
from common.djangoapps.student.models import CourseEnrollment
from opaque_keys.edx.keys import CourseKey


log = logging.getLogger("edx.student")


def create_user(
    username: str,
    email: str,
    first_name: str,
    last_name: str,
    password: str,
) -> User:
    """
    Create a new Open edX user account.
    """

    log.info(
        "Creating new user account | email=%s username=%s",
        email,
        username,
    )

    form = AccountCreationForm(
        data={
            "username": username,
            "email": email,
            "password": password,
            "name": f"{first_name} {last_name}",
        },
        tos_required=False,
    )

    user, _, _ = do_create_account(form)

    user.first_name = first_name
    user.last_name = last_name
    user.is_active = True
    user.save(update_fields=[
        "first_name",
        "last_name",
        "is_active",
    ])

    log.info(
        "User created successfully | user_id=%s",
        user.id,
    )

    return user


def deactivate_enrollments(
    user: User,
    course_key: str | None = None,
) -> None:
    """
    Deactivate existing course enrollments.
    """

    enrollments = CourseEnrollment.objects.filter(
        user=user,
    )

    if course_key:
        enrollments = enrollments.filter(
            course_id=CourseKey.from_string(course_key),
        )

    updated = enrollments.update(
        is_active=False,
    )

    log.info(
        "Enrollments deactivated | user_id=%s count=%s",
        user.id,
        updated,
    )


def generate_username(email: str) -> str:
    """
    Generate username from email address.
    """

    username = email.split("@")[0]

    username = re.sub(r'[^a-zA-Z0-9]', '_', username)

    return username[:30]


def generate_random_password(user: User | None = None) -> str:
    """
    Generate a password compatible with Open edX validators.
    """

    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    numbers = string.digits
    symbols = "!@#$%^&*()-_=+"

    characters = (
        lowercase
        + uppercase
        + numbers
        + symbols
    )

    while True:
        password_chars = [
            secrets.choice(lowercase),
            secrets.choice(uppercase),
            secrets.choice(numbers),
            secrets.choice(symbols),
        ]

        password_chars.extend(
            secrets.choice(characters)
            for _ in range(12)
        )

        secrets.SystemRandom().shuffle(password_chars)

        password = "".join(password_chars)

        try:
            validate_password(
                password,
                user=user,
            )

            return password

        except ValidationError:
            continue
import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_enrollment_email(
    user: User,
    password: str,
    mail_details: dict,
) -> None:
    """
    Send enrollment email.

    Priority:
        1. Dashboard Notify API (if configured)
        2. Django Email Backend (fallback)
    """

    subject = mail_details.get("subject")
    template_name = mail_details.get("body_template_name")

    from_address = (
        mail_details.get("from_address")
        or configuration_helpers.get_value(
            "CONTACT_EMAIL",
            settings.CONTACT_EMAIL,
            "no-reply@alv.talentsprint.com",
        )
    )

    support_email = configuration_helpers.get_value(
        "CONTACT_EMAIL",
        settings.CONTACT_EMAIL,
    )

    lms_root_url = (
        mail_details.get("lms_url")
        or configuration_helpers.get_value(
            "LMS_ROOT_URL",
            settings.LMS_ROOT_URL,
        )
    )

    context = {
        "first_name": user.first_name,
        "support_email": support_email,
        "password": password,
        "email": user.email,
        "lms_root_url": lms_root_url,
    }

    try:
        message = render_to_string(template_name, context)
    except Exception:
        log.exception("Failed to render email template: %s", template_name)
        raise

    dashboard_url = configuration_helpers.get_value(
        "DASHBOARD_URL",
        getattr(settings, "DASHBOARD_URL", ""),
        "https://dashboard.talentsprint.com",
    )

    notify_config = configuration_helpers.get_value(
        "DASHBOARD_NOTIFY_USER",
        getattr(settings, "DASHBOARD_NOTIFY_USER", {}),
        {},
    )

    notify_password = notify_config.get("NOTIFY_PASSWORD")
    notify_endpoint = notify_config.get("NOTIFY_USER_ENDPOINT")
    retries = notify_config.get("RETRIES", 3)

    use_notify_service = all(
        [
            dashboard_url,
            notify_password,
            notify_endpoint,
        ]
    )

    if use_notify_service:
        url = (
            f"{dashboard_url.rstrip('/')}/"
            f"{notify_endpoint.lstrip('/')}"
        )

        payload = {
            "mail_recipient": [user.email],
            "cc": mail_details.get("cc_addresses", []),
            "bcc": mail_details.get("bcc_addresses", []),
            "subject": subject,
            "mail_content": message,
            "from_email": from_address,
            "NOTIFY_PASSWORD": notify_password,
        }

        for attempt in range(1, retries + 1):
            try:
                log.info(
                    "Sending enrollment email via Notify API | "
                    "user_id=%s | attempt=%s",
                    user.id,
                    attempt,
                )

                response = requests.post(
                    url,
                    data=payload,
                    timeout=5,
                )

                response.raise_for_status()

                log.info(
                    "Enrollment email sent via Notify API | "
                    "user_id=%s | status=%s | response=%s",
                    user.id,
                    response.status_code,
                    response.text,
                )
                return

            except requests.RequestException:
                log.exception(
                    "Notify API failed | user_id=%s | attempt=%s",
                    user.id,
                    attempt,
                )

        log.warning(
            "Notify API unavailable after %s attempts. "
            "Falling back to Django email backend.",
            retries,
        )

    email = EmailMultiAlternatives(
        subject=subject,
        body="",
        from_email=from_address,
        to=[user.email],
        cc=mail_details.get("cc_addresses", []),
        bcc=mail_details.get("bcc_addresses", []),
    )

    email.attach_alternative(
        message,
        "text/html",
    )

    email.send(fail_silently=False)

    log.info(
        "Enrollment email sent via Django backend | user_id=%s",
        user.id,
    )