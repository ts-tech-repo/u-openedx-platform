from django.core.management.base import BaseCommand

from custom_lms.sync import run_sync
from custom_lms.models import AvSyncHistory
from openedx.core.djangoapps.content.block_structure.management.commands.generate_course_blocks import (
    get_mutually_exclusive_required_option,
)


class Command(BaseCommand):
    help = "Recomputes CMU Admin Dashboard cache tables (av_learners, av_summary)."

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
        trigger = (
            AvSyncHistory.TRIGGER_MANUAL
            if options["manual"]
            else AvSyncHistory.TRIGGER_CRON
        )

        courses_mode = get_mutually_exclusive_required_option(
            options,
            "courses",
        )

        course_ids = None

        if courses_mode == "courses":
            raw_courses = options.get("courses") or []

            course_ids = []

            for course in raw_courses:
                if not course:
                    continue

                # Support comma-separated values.
                for course_id in course.split(","):
                    course_id = course_id.strip()

                    # Remove accidental surrounding brackets.
                    course_id = course_id.strip("[]")

                    if course_id:
                        course_ids.append(course_id)

            # Remove duplicates while preserving order.
            course_ids = list(dict.fromkeys(course_ids))

        print(
            f"Running CMU dashboard sync "
            f"(trigger={trigger}, courses_mode={courses_mode})"
        )

        print(f"Course IDs: {course_ids}")

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