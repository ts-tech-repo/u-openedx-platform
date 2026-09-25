import fcntl
import os

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from custom_lms.sync import run_sync
from custom_lms.models import AvSyncHistory
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview

class Command(BaseCommand):
    help = "Recomputes CMU Admin Dashboard cache tables (av_learners, av_summary)."

    # The lock is automatically released by the operating system when the
    # process finishes, crashes, or is terminated.
    LOCK_FILE_PATH = "/tmp/cmu_admin_dashboard_sync.lock"

    def add_arguments(self, parser):
        parser.add_argument(
            "--manual",
            action="store_true",
            help="Mark this run as manually triggered rather than cron.",
        )

        parser.add_argument(
            "--courses",
            dest="courses",
            nargs="+",
            help=(
                "Recompute only the specified course IDs. "
                "Supports space-separated or comma-separated values."
            ),
        )

        parser.add_argument(
            "--force_update",
            action="store_true",
            default=False,
            help="Force update all rows, even if the data has not changed.",
        )

    def handle(self, *args, **options):
        """
        Acquire an exclusive non-blocking lock before starting the sync.

        If another sync process already holds the lock, this execution is
        skipped immediately instead of waiting.
        """
        lock_file = None
        lock_acquired = False

        try:
            # Use a+ so merely opening the file does not erase the information
            # written by the process currently holding the lock.
            lock_file = open(
                self.LOCK_FILE_PATH,
                "a+",
                encoding="utf-8",
            )

            try:
                fcntl.flock(
                    lock_file.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,
                )
                lock_acquired = True

            except BlockingIOError:
                self.stdout.write(
                    self.style.WARNING(
                        "A previous CMU dashboard sync is still running. "
                        "Skipping this execution."
                    )
                )
                return

            # The lock was acquired successfully. Replace any old lock-file
            # information with details about the current process.
            lock_file.seek(0)
            lock_file.truncate()

            lock_file.write(
                f"pid={os.getpid()}\n"
                f"started_at={timezone.now().isoformat()}\n"
            )
            lock_file.flush()

            self.stdout.write(
                f"Acquired sync lock: {self.LOCK_FILE_PATH}"
            )

            self._execute_sync(options)

        finally:
            if lock_file is not None:
                if lock_acquired:
                    try:
                        # Clear diagnostic information before releasing.
                        lock_file.seek(0)
                        lock_file.truncate()
                        lock_file.flush()

                        fcntl.flock(
                            lock_file.fileno(),
                            fcntl.LOCK_UN,
                        )

                        self.stdout.write(
                            "Released CMU dashboard sync lock."
                        )

                    except (OSError, ValueError) as exc:
                        self.stderr.write(
                            self.style.WARNING(
                                f"Unable to cleanly release the sync lock: {exc}"
                            )
                        )

                lock_file.close()

    def _execute_sync(self, options):
        """
        Prepare the course IDs and execute the dashboard synchronization.
        """
        trigger = (
            AvSyncHistory.TRIGGER_MANUAL
            if options["manual"]
            else AvSyncHistory.TRIGGER_CRON
        )

        courses_mode = "courses" if options.get("courses") else None

        course_ids = None

        if courses_mode == "courses":
            course_ids = self._parse_course_ids(
                options.get("courses") or []
            )
        else:
            course_ids = self._get_active_course_ids()

        self.stdout.write(
            "Running CMU dashboard sync "
            f"(trigger={trigger}, courses_mode={courses_mode})"
        )

        self.stdout.write(
            f"Course IDs: {course_ids}"
        )

        history = run_sync(
            trigger=trigger,
            course_ids=course_ids,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Sync {history.status}: "
                f"{history.courses_processed} course(s), "
                f"{history.learners_processed} learner row(s), "
                f"{history.duration_seconds}s"
            )
        )

    @staticmethod
    def _parse_course_ids(raw_courses):
        """
        Parse space-separated and comma-separated course IDs.

        Example:
            --courses course-v1:A course-v1:B,course-v1:C
        """
        course_ids = []

        for course in raw_courses:
            if not course:
                continue

            for course_id in course.split(","):
                course_id = course_id.strip()
                course_id = course_id.strip("[]")
                course_id = course_id.strip()

                if course_id:
                    course_ids.append(course_id)

        # Remove duplicates while preserving the original order.
        return list(dict.fromkeys(course_ids))

    @staticmethod
    def _get_active_course_ids():
        """
        Return courses that have started and have not yet ended.
        """
        now = timezone.now()

        active_courses = (
            CourseOverview.objects
            .filter(start__lte=now)
            .filter(
                Q(end__isnull=True)
                | Q(end__gt=now)
            )
            .values_list("id", flat=True)
        )

        return [
            str(course_id)
            for course_id in active_courses
        ]