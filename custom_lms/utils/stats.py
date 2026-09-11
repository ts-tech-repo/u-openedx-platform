import logging

from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from common.djangoapps.student.models.course_enrollment import CourseEnrollment
from custom_lms.models.admin_view import AvLearners, AvSummary
from custom_lms.views.eligibility import is_eligible_for_certificate, get_course_progress_percent
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview

log = logging.getLogger(__name__)

LAST_LOGIN_ACTIVE_THRESHOLD_HOURS = getattr(settings, "LAST_LOGIN_ACTIVE_THRESHOLD_HOURS", 168) # 24 * 7 = 168 hours = 1 week

def _get_course_name(course_key):
    """
    Returns the course name for the given course key.
    """
    try:
        course_overview = CourseOverview.objects.get(id=course_key)
        return course_overview.display_name
    except CourseOverview.DoesNotExist as e:
        log.error("CourseOverview for %s not found: %s", course_key, str(e))
        return str(course_key)  # Fallback to course key string if not found

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
    """
    Fetches dashboard statistics for a given course.
    Returns a dictionary with the following keys:
        - course_name: str
        - total_learners: int
        - completion_rate: float
        - active_users: int
        - avg_kc_completed: float
        - kc_total: int
    """
    log.info("Fetching dashboard stats for course=%s", course_key)
    
    course_name = _get_course_name(course_key)
    log.info("Course name for course=%s: %s", course_key, course_name)

    summary = (
        AvSummary.objects
        .filter(course_id=course_key)
        .values(
            "enrolled_count",
            "completion_rate",
            "active_learners_count",
            "av_checkpoints_completed",
            "checkpoints_total",
        )
        .first()
    )

    if not summary:
        log.warning("No AvSummary found for course=%s", course_key)
        result = {
            "course_name": course_name,
            "total_learners": 0,
            "completion_rate": 0,
            "active_users": 0,
            "avg_kc_completed": 0,
            "kc_total": 0,
        }
        return result

    total_learners = summary["enrolled_count"]

    result = {
        "course_name": course_name,
        "total_learners": total_learners,
        "completion_rate": summary["completion_rate"],
        "active_users": summary["active_learners_count"],
        "avg_kc_completed": round(
            summary["av_checkpoints_completed"] / total_learners,
            2,
        ) if total_learners else 0,
        "kc_total": summary["checkpoints_total"],
    }

    log.info(
        "Dashboard stats for course=%s: learners=%s, completion_rate=%s%%, "
        "active_users=%s, avg_kc_completed=%s, kc_total=%s",
        course_key,
        result["total_learners"],
        result["completion_rate"],
        result["active_users"],
        result["avg_kc_completed"],
        result["kc_total"],
    )
    return result


def get_learner_rows(course_key):
    """"
    Fetches rows of learner data for a given course.
    Returns a list of dictionaries, each containing:
        - user_id: int
        - name: str
        - email: str
        - enrolled_on: datetime
        - course_progress: float
        - kc_completed: int
        - kc_total: int
        - last_login: datetime
        - program_status: str ("Completed" or "In Progress")
    """
    log.info("Fetching learner rows for course=%s", course_key)

    learners = list(
        AvLearners.objects
        .filter(course_id=course_key)
        .values(
            "user_id",
            "user__email",
            "name",
            "enrolled_on",
            "course_progress",
            "checkpoints_completed",
            "checkpoints_total",
            "last_login",
            "program_status",
        )
        .order_by("name")
    )

    result = [
        {
            "user_id": learner["user_id"],
            "name": learner["name"],
            "email": learner["user__email"],
            "enrolled_on": learner["enrolled_on"],
            "course_progress": learner["course_progress"],
            "kc_completed": learner["checkpoints_completed"],
            "kc_total": learner["checkpoints_total"],
            "last_login": learner["last_login"],
            "program_status": (
                "Completed"
                if learner["program_status"] == AvLearners.STATUS_COMPLETED
                else "In Progress"
            ),
        }
        for learner in learners
    ]

    log.info(
        "Learner rows completed for course=%s: rows=%s",
        course_key,
        len(result),
    )

    return result