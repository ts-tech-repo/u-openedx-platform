# custom_lms/apps/cmu_dashboard/views.py
import csv
import logging

from django.http import HttpResponse
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.response import Response

from opaque_keys.edx.keys import CourseKey

from custom_lms.models.learner_survey import LearnerSurvey
from custom_lms.utils.permissions import IsInstructorOrAdmin
from custom_lms.utils.stats import get_dashboard_stats, get_learner_rows

log = logging.getLogger(__name__)


class DashboardStatsView(APIView):
    permission_classes = [IsInstructorOrAdmin]

    def get(self, request):
        course_key = CourseKey.from_string(request.query_params['course_id'])
        return Response(get_dashboard_stats(course_key))


class LearnerListView(APIView):
    permission_classes = [IsInstructorOrAdmin]

    def get(self, request):
        course_key = CourseKey.from_string(request.query_params['course_id'])
        return Response(get_learner_rows(course_key))


class LearnerProgressExportView(APIView):
    """
    GET /extras/api/v1/export/learners-progress/?course_id=...

    Returns a CSV file with one row per enrolled learner, matching the
    format:

        Name, Date of Enrolment, Course Progress, KC Completed (>60%),
        Last Login, Program Status
    """
    permission_classes = [IsInstructorOrAdmin]

    # ------------------------------------------------------------------ #
    # Formatting helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fmt_date(dt):
        """'12 Sep 2025' — day without zero-padding."""
        if not dt:
            return ''
        local_dt = timezone.localtime(dt) if timezone.is_aware(dt) else dt
        return local_dt.strftime('%-d %b %Y')

    @staticmethod
    def _fmt_last_login(dt):
        """'11 Sept 2026, 10:39 am' — matches the sample CSV."""
        if not dt:
            return ''
        local_dt = timezone.localtime(dt) if timezone.is_aware(dt) else dt
        # %-I  — hour without leading zero
        # %p   — AM/PM; lower() gives am/pm
        return local_dt.strftime('%-d %b %Y, %-I:%M ') + local_dt.strftime('%p').lower()

    # ------------------------------------------------------------------ #

    def get(self, request):
        course_id = request.query_params.get('course_id')
        if not course_id:
            return Response({'error': 'course_id is required'}, status=400)

        course_key = CourseKey.from_string(course_id)
        rows = get_learner_rows(course_key)

        response = HttpResponse(content_type='text/csv')
        filename = f"learner-progress-{course_id}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response, quoting=csv.QUOTE_ALL)

        # Header — must match the reference CSV exactly
        writer.writerow([
            'Name',
            'Date of Enrolment',
            'Course Progress',
            'KC Completed (>60%)',
            'Last Login',
            'Program Status',
        ])

        for row in rows:
            writer.writerow([
                row.get('name', ''),
                self._fmt_date(row.get('enrolled_on')),
                f"{row.get('course_progress', 0)}%",
                f"{row.get('kc_completed', 0)}/{row.get('kc_total', 0)}",
                self._fmt_last_login(row.get('last_login')),
                row.get('program_status', ''),
            ])

        log.info(
            "LearnerProgressExportView | course_id=%s | rows=%d | user=%s",
            course_id,
            len(rows),
            request.user.username,
        )
        return response


class SurveyResponsesExportView(APIView):
    """
    GET /extras/api/v1/export/survey-responses/?course_id=...

    Returns a CSV file with one row per submitted survey response, matching
    the format:

        ID, Survey Name, Source, Submitted At,
        <question 1>, <question 2>, <question 3>, <question 4>,
        Is there anything that would enhance your experience in the program?
    """
    permission_classes = [IsInstructorOrAdmin]

    # Survey display metadata — kept here so it's easy to move to settings
    # later without touching the query logic.
    SURVEY_NAME = 'CMU Survey'
    SURVEY_SOURCE = 'cmu-survey'

    QUESTIONS = [
        (
            'The program helped me develop skills and knowledge needed to '
            'understand, evaluate, and apply AI in my organization.'
        ),
        (
            'The action plans and capstone helped me translate program '
            'learning into a practical path for AI implementation in my organization.'
        ),
        'I would recommend the program to a colleague or friend.',
        'Considering the time and money invested, this program was a good value.',
        'Is there anything that would enhance your experience in the program?',
    ]

    # ------------------------------------------------------------------ #
    # Formatting helpers                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fmt_submitted_at(dt):
        """'28/8/2026, 11:23:12 am' — matches the reference CSV."""
        if not dt:
            return ''
        local_dt = timezone.localtime(dt) if timezone.is_aware(dt) else dt
        date_part = local_dt.strftime('%-d/%-m/%Y')
        time_part = local_dt.strftime('%-I:%M:%S ') + local_dt.strftime('%p').lower()
        return f"{date_part}, {time_part}"

    # ------------------------------------------------------------------ #

    def get(self, request):
        course_id = request.query_params.get('course_id')
        if not course_id:
            return Response({'error': 'course_id is required'}, status=400)

        course_key = CourseKey.from_string(course_id)

        surveys = (
            LearnerSurvey.objects
            .filter(
                course_id=course_key,
                action=LearnerSurvey.ACTION_SURVEY_SUBMIT,
            )
            .select_related('user')
            .order_by('-created_at')
        )

        response = HttpResponse(content_type='text/csv')
        filename = f"survey-responses-{course_id}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response, quoting=csv.QUOTE_ALL)

        # Header
        writer.writerow(['ID', 'Survey Name', 'Source', 'Submitted At'] + self.QUESTIONS)

        for survey in surveys:
            # Build a lookup from question text → answer for this submission
            answers_lookup = {
                item.get('question', ''): item.get('answer', '') if item.get('comment') is None else f"{item.get('answer', '')} ({item.get('comment')})"
                for item in survey.answers          # property defined on the model
            }

            answer_cells = [answers_lookup.get(q, '') for q in self.QUESTIONS]

            writer.writerow([
                f"sr-{survey.survey_uuid.int % (10 ** 16)}",   # deterministic short ID
                self.SURVEY_NAME,
                self.SURVEY_SOURCE,
                self._fmt_submitted_at(survey.created_at),
                *answer_cells,
            ])

        log.info(
            "SurveyResponsesExportView | course_id=%s | rows=%d | user=%s",
            course_id,
            surveys.count(),
            request.user.username,
        )
        return response