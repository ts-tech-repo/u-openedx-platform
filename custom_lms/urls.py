"""
Mount in your project urls.py, e.g.:

    urlpatterns += [
        path("extras/", include("custom_lms.urls", namespace="custom_lms")),
    ]
"""

from django.urls import path

from custom_lms.api import learner_survey 

app_name = "custom_lms"

urlpatterns = [
    path("certificate/status/", learner_survey.certificate_status, name="certificate-status"),
    path("certificate/generate/", learner_survey.certificate_generation_view, name="certificate-generate"),
    path("certificate/view/", learner_survey.certificate_view, name="certificate-view"),
    path("certificate/download/", learner_survey.certificate_download, name="certificate-download"),
    path("survey/submit/", learner_survey.submit_survey, name="survey-submit"),
]