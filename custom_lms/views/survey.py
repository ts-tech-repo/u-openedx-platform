"""
Views for the survey app.

- SurveyStatusView  (GET)  -> has this learner already responded / skipped?
- SurveySubmitView  (POST) -> create or update the learner's response.

Both return a `redirect_url` the frontend should navigate to (or load in
an iframe) once the learner is done with the survey — e.g. back to the
course courseware, a "thank you" page, etc.
"""

from django.conf import settings
from django.urls import reverse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SurveyResponse
from .serializers import SurveyResponseSerializer, SurveySubmitSerializer


def _build_redirect_url(request, course_id):
    """
    Where should the learner land after they submit/skip the survey?

    Priority:
      1. An explicit `next` / `redirect_url` the frontend already knows
         about (sent as a query param on GET, or in the POST body).
      2. SURVEY_DEFAULT_REDIRECT_URL_TEMPLATE from settings, e.g.
         "/courses/{course_id}/course/" — filled in with the course id.
      3. A generic named URL, if your app has one (edit `course_root`
         below to whatever your courseware's URL name actually is).

    Adjust this to match how "Ulmo" resolves course home / dashboard
    URLs in your deployment.
    """
    next_url = request.GET.get("next") or request.data.get("redirect_url") \
        if hasattr(request, "data") else request.GET.get("next")

    if next_url:
        return next_url

    template = getattr(
        settings,
        "SURVEY_DEFAULT_REDIRECT_URL_TEMPLATE",
        None,
    )
    if template:
        return template.format(course_id=course_id)

    try:
        return reverse("course_root", kwargs={"course_id": course_id})
    except Exception:  # noqa: BLE001 - reverse() raises NoReverseMatch
        return "/"


class SurveyStatusView(APIView):
    """
    GET /api/survey/status/?course_id=...&survey_id=...

    Tells the frontend whether the current learner has already
    completed (or skipped) this survey, so the template can skip
    rendering the form and go straight to `redirect_url` if so.

    Response:
        {
            "submitted": true,
            "skipped": false,
            "redirect_url": "...",
            "response": { ...SurveyResponseSerializer... } | null
        }
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        course_id = request.query_params.get("course_id")
        survey_id = request.query_params.get("survey_id")

        if not course_id or not survey_id:
            return Response(
                {"error": "course_id and survey_id are required query params."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = SurveyResponse.objects.filter(
            user_id=request.user.id,
            course_id=course_id,
            survey_id=survey_id,
        ).first()

        if not existing:
            return Response(
                {
                    "submitted": False,
                    "skipped": False,
                    "redirect_url": None,
                    "response": None,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {
                "submitted": not existing.skipped,
                "skipped": existing.skipped,
                "redirect_url": _build_redirect_url(request, course_id),
                "response": SurveyResponseSerializer(existing).data,
            },
            status=status.HTTP_200_OK,
        )


class SurveySubmitView(APIView):
    """
    POST /api/survey/submit/

    Body:
        {
            "course_id": "course-v1:Org+Course+Run",
            "survey_id": "post-course-feedback",
            "skip_survey": false,
            "answers": [
                {"question": "1. The program helped me...", "answer": "Agree"},
                ...
            ]
        }

    For a skip, the body only needs:
        {
            "course_id": "...",
            "survey_id": "...",
            "skip_survey": true
        }

    Response:
        {
            "success": true,
            "message": "...",
            "redirect_url": "...",   <- frontend renders this on the same
                                          page or loads it in an iframe
            "id": 123
        }
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SurveySubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        course_id = data["course_id"]
        survey_id = data["survey_id"]
        skipped = data.get("skip_survey", False)
        answers = data.get("answers", [])

        survey_response, _created = SurveyResponse.objects.update_or_create(
            user_id=request.user.id,
            course_id=course_id,
            survey_id=survey_id,
            defaults={
                "response_json": answers,
                "skipped": skipped,
            },
        )

        redirect_url = _build_redirect_url(request, course_id)

        message = (
            "The survey was skipped successfully."
            if skipped
            else "Your survey response was submitted successfully."
        )

        return Response(
            {
                "success": True,
                "message": message,
                "redirect_url": redirect_url,
                "id": survey_response.id,
            },
            status=status.HTTP_200_OK,
        )