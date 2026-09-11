"""
Mount in your project urls.py, e.g.:

    urlpatterns += [
        path("extras/", include("custom_lms.urls", namespace="custom_lms")),
    ]
"""

from django.urls import path

from custom_lms.api import learner_survey
from custom_lms.views.admin_view import (
    DashboardStatsView,
    LearnerListView,
    LearnerProgressExportView,
    SurveyResponsesExportView,
)

app_name = "custom_lms"

urlpatterns = [
    path("certificate/status/", learner_survey.certificate_status, name="certificate-status"),
    path("certificate/generate/", learner_survey.certificate_generation_view, name="certificate-generate"),
    path("certificate/download/", learner_survey.certificate_download, name="certificate-download"),
    path("survey/submit/", learner_survey.submit_survey, name="survey-submit"),
    path('api/v1/stats/', DashboardStatsView.as_view(), name='cmu_dashboard_stats'),
    path('api/v1/learners/', LearnerListView.as_view(), name='cmu_dashboard_learners'),
    path('api/v1/export/learners-progress/', LearnerProgressExportView.as_view(), name='export_learner_progress'),
    path('api/v1/export/survey-responses/', SurveyResponsesExportView.as_view(), name='export_survey_responses'),
]