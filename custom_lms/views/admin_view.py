# custom_lms/apps/cmu_dashboard/views.py
from custom_lms.utils.permissions import IsInstructorOrAdmin
from custom_lms.utils.stats import get_dashboard_stats, get_learner_rows
from rest_framework.views import APIView
from rest_framework.response import Response
from opaque_keys.edx.keys import CourseKey


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