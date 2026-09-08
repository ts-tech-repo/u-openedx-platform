import logging

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from common.djangoapps.student.models.course_enrollment import CourseEnrollment
from custom_lms.views.eligibility import is_eligible_for_certificate, get_course_progress_percent

log = logging.getLogger(__name__)

LAST_LOGIN_ACTIVE_THRESHOLD_HOURS = getattr(settings, "LAST_LOGIN_ACTIVE_THRESHOLD_HOURS", 168) # 24 * 7 = 168 hours = 1 week

def _get_checkpoints_completed(user, course_key):
    """
    Returns the number of checkpoints completed by the user
    in the given course.
    """
    completed = 0
    total = 0

    _, eligibility = is_eligible_for_certificate(user, course_key)

    log.info(
        "Eligibility for user %s in course %s: %s",
        user.username,
        course_key,
        eligibility,
    )

    # Check None BEFORE calling .get()
    if not eligibility:
        return 0, 0

    graded_subsections = eligibility.get("graded_subsections", [])

    if not graded_subsections:
        return 0, 0

    for checkpoint in graded_subsections:
        log.info(
            "Checkpoint %s for user %s in course %s: passed=%s",
            checkpoint.get("display_name"),
            user.username,
            course_key,
            checkpoint.get("passed", False),
        )

        total += 1

        if checkpoint.get("passed", False):
            completed += 1

    return total, completed

def is_active_user(user_profile_last_login):
    if not user_profile_last_login:
        return False
    return timezone.now() - user_profile_last_login <= timedelta(hours=LAST_LOGIN_ACTIVE_THRESHOLD_HOURS)

def get_dashboard_stats(course_key):
    enrollments = CourseEnrollment.objects.filter(
        course_id=course_key, is_active=True
    ).select_related('user', 'user__profile')

    total_learners = enrollments.count()
    if total_learners == 0:
        return {
            "total_learners": 0, "completion_rate": 0,
            "active_users": 0, "avg_kc_completed": 0,
            "kc_total": 0,
        }

    completed_count = 0
    active_count = 0
    kc_sum = 0
    expected_checkpoints = 0

    for enrollment in enrollments:
        user = enrollment.user
        
        expected_checkpoints, completed_checkpoints = _get_checkpoints_completed(user, course_key)
        kc_sum += completed_checkpoints
        if completed_checkpoints >= expected_checkpoints:
            completed_count += 1
            
        if is_active_user(getattr(user, 'last_login', None)):
            active_count += 1

    return {
        "total_learners": total_learners,
        "completion_rate": round((completed_count / total_learners) * 100),
        "active_users": active_count,
        "avg_kc_completed": round(kc_sum / total_learners, 2),
        "kc_total": expected_checkpoints,
    }


def get_learner_rows(course_key):
    enrollments = CourseEnrollment.objects.filter(
        course_id=course_key, is_active=True
    ).select_related('user', 'user__profile')

    rows = []
    for enrollment in enrollments:
        user = enrollment.user
        expected_checkpoints, completed_checkpoints = _get_checkpoints_completed(user, course_key)
        rows.append({
            "user_id": user.id,
            "name": user.profile.name if hasattr(user, 'profile') else user.username,
            "enrolled_on": enrollment.created,
            "course_progress": get_course_progress_percent(user, course_key),
            "kc_completed": completed_checkpoints,
            "kc_total": expected_checkpoints,
            "last_login": user.last_login,
            "program_status": "Completed" if completed_checkpoints >= expected_checkpoints else "In Progress",
        })
    return rows