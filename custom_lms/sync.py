# custom_lms/apps/cmu_dashboard/sync.py
import logging
import time
from django.utils import timezone
from django.conf import settings 
from custom_lms.utils.stats import _get_checkpoints_completed, get_course_progress_percent, is_active_user
from common.djangoapps.student.models import CourseEnrollment
from custom_lms.models import AvLearners, AvSummary, AvSyncHistory


log = logging.getLogger(__name__)


def run_sync(trigger=AvSyncHistory.TRIGGER_CRON, course_ids=None):
    """
    Recomputes AvLearners + AvSummary for every course with active
    enrollments (or a specific list of course_ids, for targeted re-syncs).
    """
    from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers

    history = AvSyncHistory.objects.create(trigger=trigger)
    start = time.monotonic()
    courses_ok = 0
    courses_failed = 0
    learners_total = 0

    course_id_qs = (
        course_ids
        or CourseEnrollment.objects.filter(is_active=True)
            .values_list('course_id', flat=True).distinct()
    )

    exclude_user_list = tuple(configuration_helpers.get_value(
        'AV_SYNC_EXCLUDE_USER_LIST', getattr(settings, 'AV_SYNC_EXCLUDE_USER_LIST', [])
    ))

    error_reason = {}

    for course_key in course_id_qs:
        try:
            learners_total += _sync_course(course_key, exclude_user_list)
            courses_ok += 1
        except Exception as e:
            error_reason[str(course_key)] = str(e)
            courses_failed += 1
            log.exception("CMU dashboard sync failed for course %s | err = %s", course_key, e)

    history.finished_at = timezone.now()
    history.duration_seconds = round(time.monotonic() - start, 2)
    history.courses_processed = courses_ok
    history.courses_failed = courses_failed
    history.learners_processed = learners_total
    history.status = (
        AvSyncHistory.STATUS_SUCCESS if courses_failed == 0
        else AvSyncHistory.STATUS_PARTIAL if courses_ok > 0
        else AvSyncHistory.STATUS_FAILED
    )
    history.error_message = error_reason
    history.save()
    return history


def _sync_course(course_key, exclude_user_list=()):
    enrollments = (
        CourseEnrollment.objects.filter(course_id=course_key, is_active=True)
        .select_related('user', 'user__profile')
    )
    total_learners = 0
    completed_count = 0
    active_count = 0

    kc_sum = 0
    kc_avg_learners = 0

    checkpoints_total = None

    seen_user_ids = []
    for enrollment in enrollments:
        user = enrollment.user

        if user is None:
            continue

        if exclude_user_list and user.email.lower().endswith(exclude_user_list):
            log.info("Skipping excluded user %s in course %s", user.email, course_key)
            continue

        if user.is_staff or user.is_superuser:
            # Skip staff/superusers, since they are not real learners.
            log.info(
                "Skipping staff/superuser %s in course %s",
                user.username,
                course_key,
            )
            continue
        expected_checkpoints, completed_checkpoints = _get_checkpoints_completed(user, course_key)
        progress = get_course_progress_percent(user, course_key)

        if checkpoints_total is None:
            checkpoints_total = expected_checkpoints

        is_completed = expected_checkpoints > 0 and completed_checkpoints >= expected_checkpoints
        status = (
            AvLearners.STATUS_NONE
            if expected_checkpoints == 0
            else AvLearners.STATUS_COMPLETED if is_completed
            else AvLearners.STATUS_IN_PROGRESS
        )

        AvLearners.objects.update_or_create(
            user=user, course_id=course_key,
            defaults=dict(
                name=user.profile.name if hasattr(user, 'profile') else f"{user.first_name} {user.last_name}".strip() or user.username,
                enrolled_on=enrollment.created,
                course_progress=progress,
                checkpoints_completed=completed_checkpoints,
                checkpoints_total=expected_checkpoints,
                last_login=user.last_login,
                program_status=status,
            ),
        )
        seen_user_ids.append(user.id)

        total_learners += 1

        if is_completed:
            completed_count += 1
        else:
            # Only learners who have NOT completed all KCs
            kc_sum += completed_checkpoints
            kc_avg_learners += 1

        if is_active_user(user.last_login):
            active_count += 1

    # Drop rows for learners who unenrolled since the last sync
    AvLearners.objects.filter(course_id=course_key).exclude(
        user_id__in=seen_user_ids
    ).delete()

    in_progress_count = total_learners - completed_count
    completion_rate = round((completed_count / total_learners) * 100, 1) if total_learners else 0

    av_checkpoints_completed = round(kc_sum / kc_avg_learners, 2) if kc_avg_learners else 0
        
    AvSummary.objects.update_or_create(
        course_id=course_key,
        defaults=dict(
            enrolled_count=total_learners,
            completed_count=completed_count,
            in_progress_count=in_progress_count,
            completion_rate=completion_rate,
            active_learners_count=active_count,
            av_checkpoints_completed=av_checkpoints_completed,
            checkpoints_total=checkpoints_total or 0,
        ),
    )
    return total_learners