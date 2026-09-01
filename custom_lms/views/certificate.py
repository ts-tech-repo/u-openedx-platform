"""
Helpers for triggering certificate generation and locating the URL of
the rendered certificate page, once a learner is eligible (see
eligibility.py) and has been through the optional survey.
"""

import logging

from django.conf import settings
from django.urls import reverse
from opaque_keys.edx.keys import CourseKey

log = logging.getLogger(__name__)


def _as_course_key(course_id):
    if isinstance(course_id, CourseKey):
        return course_id
    return CourseKey.from_string(course_id)


def generate_certificate(user, course_id):
    """
    Kick off (or re-use, if already generated) certificate generation
    for this learner/course.

    Wraps edx-platform's certificate generation entry point. Confirm
    this import path against "Ulmo"'s certificates app — it's moved
    around across Open edX releases.
    """
    from lms.djangoapps.certificates.api import generate_user_certificates  # edx-platform import

    course_key = _as_course_key(course_id)

    try:
        generate_user_certificates(user, course_key)
    except Exception:  # noqa: BLE001
        log.exception(
            "Certificate generation failed for user_id=%s course_id=%s",
            user.id, course_key,
        )
        raise


def get_certificate_view_url(request, course_id):
    """
    URL of the page the learner should land on / see in the iframe
    once their certificate is ready (renders survey_completion.html,
    which <%inherit>s cmu_certificate.html).
    """
    course_key = _as_course_key(course_id)

    template = getattr(settings, "SURVEY_CERTIFICATE_VIEW_URL_TEMPLATE", None)
    if template:
        return template.format(course_id=str(course_key))

    return request.build_absolute_uri(
        f"{reverse('custom_lms:certificate-view')}?course_id={course_key}"
    )