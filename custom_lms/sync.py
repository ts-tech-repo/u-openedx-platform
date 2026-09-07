# custom_lms/apps/cmu_dashboard/sync.py
import logging
import time
from django.utils import timezone
from custom_lms.utilities.stats import _get_checkpoints_completed, get_course_progress_percent, is_active_user
from student.models import CourseEnrollment
from custom_lms.models import AvLearners, AvSummary, AvSyncHistory


log = logging.getLogger(__name__)


def run_sync(trigger=AvSyncHistory.TRIGGER_CRON, course_ids=None):
    """
    Recomputes AvLearners + AvSummary for every course with active
    enrollments (or a specific list of course_ids, for targeted re-syncs).
    """
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

    for course_key in course_id_qs:
        try:
            learners_total += _sync_course(course_key, history)
            courses_ok += 1
        except Exception:
            courses_failed += 1
            log.exception("CMU dashboard sync failed for course %s", course_key)

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
    history.save()
    return history


def _sync_course(course_key, history):
    enrollments = (
        CourseEnrollment.objects.filter(course_id=course_key, is_active=True)
        .select_related('user', 'user__profile')
    )
    now = timezone.now()
    total_learners = 0
    completed_count = 0
    active_count = 0
    kc_sum = 0

    seen_user_ids = []
    for enrollment in enrollments:
        user = enrollment.user
        expected_checkpoints, completed_checkpoints = _get_checkpoints_completed(user, course_key)
        progress = get_course_progress_percent(user, course_key)
        status = (
            AvLearners.STATUS_COMPLETED if completed_checkpoints >= expected_checkpoints
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
                last_synced_at=now,
                sync_history=history,
            ),
        )
        seen_user_ids.append(user.id)

        total_learners += 1
        kc_sum += completed_checkpoints
        if completed_checkpoints >= expected_checkpoints:
            completed_count += 1
        if is_active_user(user.last_login):
            active_count += 1

    # Drop rows for learners who unenrolled since the last sync
    AvLearners.objects.filter(course_id=course_key).exclude(
        user_id__in=seen_user_ids
    ).delete()

    AvSummary.objects.update_or_create(
        course_id=course_key,
        defaults=dict(
            total_learners=total_learners,
            completion_rate=round((completed_count / total_learners) * 100, 1) if total_learners else 0,
            active_users=active_count,
            avg_kc_completed=round(kc_sum / total_learners, 2) if total_learners else 0,
            kc_total=expected_checkpoints,
            last_synced_at=now,
            sync_history=history,
        ),
    )
    return total_learners