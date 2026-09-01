"""
API + page views for custom_lms's survey-then-certificate flow.

Flow:

    Course Progress page
        -> GET certificate_status         (is the button enabled? has
                                             the survey already been
                                             answered?)
        -> [button click] load survey_page or certificate_view in an
           iframe, depending on certificate_status's answer
        -> inside that iframe: POST submit_survey  (submit or skip)
        -> submit_survey generates the certificate and hands back
           redirect_url, which the iframe navigates itself to
           (survey.html's own goToResult() handles this)
"""

import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from custom_lms.certificate import generate_certificate, get_certificate_view_url
from custom_lms.eligibility import is_eligible_for_certificate
from custom_lms.models.survey import SurveyResponse

from openedx.core.djangoapps.site_configuration import (
    helpers as configuration_helpers,
)
import logging

log = logging.getLogger(__name__)

# The single survey shown before certificate issuance. Swap for a
# per-course/config-driven id if this grows beyond one survey.
CERTIFICATE_SURVEY_ID = "course-completion-survey"

# Static per PRD's sample certificate; override per-course/program via
# settings if you end up serving more than one program off this app.
DEFAULT_PROGRAM_NAME = configuration_helpers.get_value('SURVEY_PROGRAM_NAME', "Agentic AI Program: Building Autonomous Systems for Real-World Applications")

DEFAULT_SUPPORT_EMAIL = configuration_helpers.get_value('contact_mailing_address', settings.CONTACT_EMAIL)


def _learner_display_name(user):
    full_name = user.get_full_name() if hasattr(user, "get_full_name") else f"{user.first_name} {user.last_name}"
    return (full_name or "").strip()


def _certificate_date_display():
    return timezone.now().strftime("%B %-d, %Y")



@login_required
@require_GET
def certificate_status(request):
    """
    GET /extras/certificate/status/?course_id=...

    Drives the Generate Certificate button on the Course Progress page:

        {
            "eligible": true,
            "eligibility": {"knowledge_checks": [...], "minimum_score": 0.6},
            "survey_required": false,
            "survey_id": "course-completion-survey",
            "redirect_url": "https://.../extras/certificate/view/?course_id=..." | null
        }

    `redirect_url` is only populated once the learner doesn't need to
    see the survey again (already submitted/skipped it) — at that
    point the certificate is (re)generated immediately so the frontend
    can jump straight to it (PRD 2.4).
    """
    course_id = request.GET.get("course_id")

    if not course_id:
        return JsonResponse({"error": "course_id is required"}, status=400)
    
    user = request.user
    log.info(f"Checking certificate status for IS STAFF: {user.is_staff} user: {user.username} in {course_id}")
    if not user:
        return JsonResponse({"error": "user not found"}, status=404)

    eligible, eligibility_details = is_eligible_for_certificate(request.user, course_id)

    if not user.is_staff or not eligible:
        return JsonResponse({
            "eligible": False,
            "eligibility": eligibility_details,
            "survey_required": False,
            "survey_id": CERTIFICATE_SURVEY_ID,
            "redirect_url": None,
        })

    already_responded = SurveyResponse.objects.filter(
        user=request.user,
        course_id=course_id,
        survey_id=CERTIFICATE_SURVEY_ID,
    ).exists()

    redirect_url = None
    if already_responded:
        generate_certificate(request.user, course_id)
        redirect_url = get_certificate_view_url(request, course_id)

    return JsonResponse({
        "eligible": True,
        "eligibility": eligibility_details,
        "survey_required": not already_responded,
        "survey_id": CERTIFICATE_SURVEY_ID,
        "redirect_url": redirect_url,
        "learner_name": _learner_display_name(request.user),
        "program_name": DEFAULT_PROGRAM_NAME,
        "certificate_date": _certificate_date_display(),
    })


@login_required
@require_POST
def submit_survey(request):
    """
    POST /extras/survey/submit/

    Body:
        {
            "survey_id": "course-completion-survey",
            "course_id": "course-v1:...",
            "action": "submit" | "skip",
            "metadata": {"answers": [{"question": "...", "answer": "..."}]}
        }

    Eligibility is re-checked server-side even though the frontend
    already gated the button on it — never trust the client. Stores
    the response, generates the certificate, and returns the
    certificate page URL as `redirect_url`.
    """
    try:
        data = json.loads(request.body)
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    survey_id = data.get("survey_id")
    course_id = data.get("course_id")
    action = data.get("action")
    metadata = data.get("metadata", {})

    if not survey_id:
        return JsonResponse({"success": False, "error": "survey_id is required"}, status=400)
    if not course_id:
        return JsonResponse({"success": False, "error": "course_id is required"}, status=400)
    if action not in ("submit", "skip"):
        return JsonResponse(
            {"success": False, "error": "action must be either submit or skip"}, status=400,
        )
    if not isinstance(metadata, dict):
        return JsonResponse({"success": False, "error": "metadata must be an object"}, status=400)

    eligible, eligibility_details = is_eligible_for_certificate(request.user, course_id)
    if not eligible:
        return JsonResponse(
            {
                "success": False,
                "error": "You have not met the eligibility requirements for a certificate yet.",
                "eligibility": eligibility_details,
            },
            status=403,
        )

    response, _created = SurveyResponse.objects.update_or_create(
        user=request.user,
        course_id=course_id,
        survey_id=survey_id,
        defaults={"action": action, "metadata": metadata},
    )

    generate_certificate(request.user, course_id)
    redirect_url = get_certificate_view_url(request, course_id)

    message = (
        "Your survey response was submitted successfully."
        if action == "submit"
        else "The survey was skipped successfully."
    )

    return JsonResponse({
        "success": True,
        "id": response.id,
        "action": response.action,
        "message": message,
        "redirect_url": redirect_url,
    })


@login_required
@require_GET
def certificate_generation_view(request):
    """
    GET /extras/certificate/generate/?course_id=...

    Renders certificate_generation.html — the single 3-step wizard
    (Verify Details -> Survey -> Certificate) the Course Progress
    page's Generate Certificate button loads in an iframe.

    The page's own on-load check calls certificate_status; if the
    survey isn't required (already answered on a previous visit), it
    jumps straight to step 3 instead of showing steps 1-2 again
    (PRD 2.4).
    """
    course_id = request.GET.get("course_id")

    if not course_id:
        return HttpResponse("course_id is required", status=400)

    return render(
        request,
        "custom_lms/certificate_generation.html",
        {
            "course_id": course_id,
            "survey_id": CERTIFICATE_SURVEY_ID,
            "learner_name": _learner_display_name(request.user),
            "program_name": DEFAULT_PROGRAM_NAME,
            "certificate_date": _certificate_date_display(),
            "support_email": DEFAULT_SUPPORT_EMAIL,
            "status_url": "/extras/certificate/status/",
            "submit_url": "/extras/survey/submit/",
            "download_url": "/extras/certificate/download/",
        },
    )


@login_required
@require_GET
def certificate_view(request):
    """
    GET /extras/certificate/view/?course_id=...

    Renders the certificate page (survey_completion.html, which
    <%inherit>s cmu_certificate.html) — this is `redirect_url` above.
    """
    course_id = request.GET.get("course_id")

    if not course_id:
        return HttpResponse("course_id is required", status=400)

    return render(
        request,
        "custom_lms/survey_completion.html",
        {"user": request.user, "course_id": course_id},
    )


@login_required
@require_GET
def certificate_download(request):
    """
    GET /extras/certificate/download/?course_id=...

    Streams the certificate PDF — called by the "Download Certificate"
    button inside survey_completion.html.
    """
    course_id = request.GET.get("course_id")

    if not course_id:
        return HttpResponse("course_id is required", status=400)

    # Plug in your actual PDF generation / storage lookup here — e.g.
    # rendering cmu_certificate.html to PDF (wkhtmltopdf / weasyprint)
    # or fetching a previously generated file from storage/edx-platform's
    # own certificate PDF pipeline.
    raise NotImplementedError(
        "Wire this up to your certificate PDF generation/storage."
    )