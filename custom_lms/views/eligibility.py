"""
Certificate eligibility checks for custom_lms.

Per the PRD: a learner is eligible for their certificate once they've
scored at least 60% on every graded "Knowledge Check" subsection in
the course.

NOTE: This wraps edx-platform's grading API (`CourseGradeFactory`).
The exact attribute names on `SubsectionGrade` (`.graded`, `.format`,
`.percent_graded`, `.display_name`) can drift slightly between Open
edX releases — verify these against the "Ulmo" release you're on and
adjust if needed. Everything else in this module is release-agnostic.
"""

import logging

from django.conf import settings
from opaque_keys.edx.keys import CourseKey

log = logging.getLogger(__name__)

# The subsection "Format" (set in Studio's "Advanced" settings for a
# graded subsection) used to identify Knowledge Checks. Override via
# Django settings if your course teams use a different label.
KNOWLEDGE_CHECK_FORMAT = getattr(
    settings, "SURVEY_KNOWLEDGE_CHECK_FORMAT", "Knowledge Check"
)

# 60% per PRD 2.1. Override via settings if this needs to be tunable
# without a code change.
MINIMUM_SCORE = getattr(settings, "SURVEY_KNOWLEDGE_CHECK_MIN_SCORE", 0.6)

from opaque_keys.edx.keys import CourseKey


def _as_course_key(course_id):
    if isinstance(course_id, CourseKey):
        return course_id
    return CourseKey.from_string(course_id)


def is_eligible_for_certificate(user, course_id):
    """
    Returns (eligible: bool, details: dict).

    `details["knowledge_checks"]` lists every graded Knowledge Check
    subsection with the learner's score and pass/fail, so the frontend
    can explain *why* the button is disabled if it wants to.
    """
    from lms.djangoapps.grades.api import CourseGradeFactory  # edx-platform import

    course_key = _as_course_key(course_id)

    try:
        course_grade = CourseGradeFactory().read(user, course_key=course_key)
    except Exception:  # noqa: BLE001
        log.exception(
            "Unable to load course grade for user_id=%s course_id=%s",
            user.id, course_key,
        )
        return False, {"knowledge_checks": [], "minimum_score": MINIMUM_SCORE, "error": "grade_unavailable"}

    knowledge_checks = []
    all_passed = True

    for subsection_grade in course_grade.subsection_grades.values():

        if not getattr(subsection_grade, "graded", False):
            continue

        subsection_format = (getattr(subsection_grade, "format", None) or "").strip().lower()
        if subsection_format != KNOWLEDGE_CHECK_FORMAT.lower():
            continue

        percent = getattr(subsection_grade, "percent_graded", None)
        if percent is None:
            # Fall back to earned/possible if percent_graded isn't
            # populated on this edx-platform version.
            possible = getattr(subsection_grade, "possible_graded", 0) or 0
            earned = getattr(subsection_grade, "earned_graded", 0) or 0
            percent = (earned / possible) if possible else 0.0

        passed = percent >= MINIMUM_SCORE
        if not passed:
            all_passed = False

        knowledge_checks.append({
            "display_name": getattr(subsection_grade, "display_name", ""),
            "percent": round(percent * 100, 1),
            "passed": passed,
        })

    # No Knowledge Checks defined in the course at all — don't block
    # certificate issuance on a requirement that doesn't exist.
    eligible = all_passed if knowledge_checks else True

    return eligible, {
        "knowledge_checks": knowledge_checks,
        "minimum_score": MINIMUM_SCORE,
    }