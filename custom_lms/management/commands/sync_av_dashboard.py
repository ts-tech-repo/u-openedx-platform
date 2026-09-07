from django.core.management.base import BaseCommand

from custom_lms.sync import run_sync
from custom_lms.models import AvSyncHistory


class Command(BaseCommand):
    help = "Recomputes CMU Admin Dashboard cache tables (av_learners, av_summary)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--course-id', action='append', dest='course_ids', default=None,
            help='Restrict sync to specific course id(s). Repeatable flag.',
        )
        parser.add_argument(
            '--manual', action='store_true',
            help='Mark this run as manually triggered rather than cron.',
        )

    def handle(self, *args, **options):
        trigger = AvSyncHistory.TRIGGER_MANUAL if options['manual'] else AvSyncHistory.TRIGGER_CRON
        history = run_sync(trigger=trigger, course_ids=options.get('course_ids'))
        self.stdout.write(self.style.SUCCESS(
            f"Sync {history.status}: {history.courses_processed} course(s), "
            f"{history.learners_processed} learner row(s), "
            f"{history.duration_seconds}s"
        ))