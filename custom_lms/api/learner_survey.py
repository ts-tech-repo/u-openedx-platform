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
from common.djangoapps.edxmako.shortcuts import render_to_response
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from custom_lms.models.survey import SurveyResponse

from custom_lms.views.certificate import generate_certificate, get_certificate_view_url
from custom_lms.views.eligibility import is_eligible_for_certificate
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
DEFAULT_PROGRAM_NAME = configuration_helpers.get_value(
    'SURVEY_PROGRAM_NAME', 
    "Agentic AI Program: Building Autonomous Systems for Real-World Applications"
)

DEFAULT_SUPPORT_EMAIL = configuration_helpers.get_value('contact_mailing_address', settings.CONTACT_EMAIL)

# Define both templates
CERTIFICATE_WIZARD_TEMPLATE = "cmu_learner_certificate.html"
CERTIFICATE_FINAL_TEMPLATE = "cmu_certificate.html"


def _learner_display_name(user):
    full_name = user.get_full_name() if hasattr(user, "get_full_name") else f"{user.first_name} {user.last_name}"
    return (full_name or "").strip()


def _certificate_date_display():
    return timezone.now().strftime("%B %-d, %Y")


def _get_certificate_context(request, course_id):
    """
    Helper to build the context required by the single-page 
    cmu_learner_certificate.html template. Both the initial load 
    and the post-survey redirect require this full context so the 
    final certificate step can properly render the learner's details.
    """
    return {
        "course_id": course_id,
        "survey_id": CERTIFICATE_SURVEY_ID,
        "learner_name": _learner_display_name(request.user),
        "program_name": DEFAULT_PROGRAM_NAME,
        "certificate_date": _certificate_date_display(),
        "support_email": DEFAULT_SUPPORT_EMAIL,
        "status_url": "/extras/certificate/status/",
        "submit_url": "/extras/survey/submit/",
        "download_url": "/extras/certificate/download/",
        "user": request.user,
    }


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
    log.info("certificate_status called | user=%s | course_id=%s", getattr(request.user, "username", None), course_id)

    if not course_id:
        log.warning("certificate_status rejected: missing course_id | user=%s", getattr(request.user, "username", None))
        return JsonResponse({"error": "course_id is required"}, status=400)

    user = request.user
    log.info(f"Checking certificate status for IS STAFF: {user.is_staff} user: {user.username} in {course_id}")
    if not user:
        log.error("certificate_status: user not found on request | course_id=%s", course_id)
        return JsonResponse({"error": "user not found"}, status=404)

    log.info("certificate_status: checking eligibility | user=%s | course_id=%s", user.username, course_id)
    eligible, eligibility_details = is_eligible_for_certificate(request.user, course_id)
    log.info(
        "certificate_status: eligibility result | user=%s | course_id=%s | eligible=%s | details=%s",
        user.username, course_id, eligible, eligibility_details,
    )

    if not user.is_staff and not eligible:
        log.info(
            "certificate_status: returning not-eligible response | user=%s | course_id=%s | is_staff=%s | eligible=%s",
            user.username, course_id, user.is_staff, eligible,
        )
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
    log.info(
        "certificate_status: survey response lookup | user=%s | course_id=%s | survey_id=%s | already_responded=%s",
        user.username, course_id, CERTIFICATE_SURVEY_ID, already_responded,
    )

    redirect_url = None
    if already_responded:
        log.info(
            "certificate_status: survey already answered, (re)generating certificate | user=%s | course_id=%s",
            user.username, course_id,
        )
        try:
            generate_certificate(request.user, course_id)
        except Exception:
            log.exception(
                "certificate_status: generate_certificate failed | user=%s | course_id=%s",
                user.username, course_id,
            )
            raise
        redirect_url = get_certificate_view_url(request, course_id)
        log.info(
            "certificate_status: certificate ready | user=%s | course_id=%s | redirect_url=%s",
            user.username, course_id, redirect_url,
        )

    response_payload = {
        "eligible": True,
        "eligibility": eligibility_details,
        "survey_required": not already_responded,
        "survey_id": CERTIFICATE_SURVEY_ID,
        "redirect_url": redirect_url,
        "learner_name": _learner_display_name(request.user),
        "program_name": DEFAULT_PROGRAM_NAME,
        "certificate_date": _certificate_date_display(),
    }
    log.info("certificate_status: response payload | user=%s | payload=%s", user.username, response_payload)
    return JsonResponse(response_payload)


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
    log.info("submit_survey called | user=%s", getattr(request.user, "username", None))

    try:
        data = json.loads(request.body)
    except (TypeError, ValueError):
        log.warning(
            "submit_survey rejected: invalid JSON body | user=%s | raw_body=%r",
            getattr(request.user, "username", None), request.body,
        )
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    survey_id = data.get("survey_id")
    course_id = data.get("course_id")
    action = data.get("action")
    metadata = data.get("metadata", {})
    log.info(
        "submit_survey payload | user=%s | survey_id=%s | course_id=%s | action=%s | metadata_keys=%s",
        request.user.username, survey_id, course_id, action,
        list(metadata.keys()) if isinstance(metadata, dict) else type(metadata).__name__,
    )

    if not survey_id:
        log.warning("submit_survey rejected: missing survey_id | user=%s", request.user.username)
        return JsonResponse({"success": False, "error": "survey_id is required"}, status=400)
    if not course_id:
        log.warning("submit_survey rejected: missing course_id | user=%s", request.user.username)
        return JsonResponse({"success": False, "error": "course_id is required"}, status=400)
    if action not in ("submit", "skip"):
        log.warning(
            "submit_survey rejected: invalid action | user=%s | action=%s", request.user.username, action,
        )
        return JsonResponse(
            {"success": False, "error": "action must be either submit or skip"}, status=400,
        )
    if not isinstance(metadata, dict):
        log.warning(
            "submit_survey rejected: metadata not an object | user=%s | metadata_type=%s",
            request.user.username, type(metadata).__name__,
        )
        return JsonResponse({"success": False, "error": "metadata must be an object"}, status=400)

    log.info(
        "submit_survey: re-checking eligibility server-side | user=%s | course_id=%s",
        request.user.username, course_id,
    )
    eligible, eligibility_details = is_eligible_for_certificate(request.user, course_id)
    log.info(
        "submit_survey: eligibility result | user=%s | course_id=%s | eligible=%s | details=%s",
        request.user.username, course_id, eligible, eligibility_details,
    )
    if not request.user.is_staff and not eligible:
        log.warning(
            "submit_survey rejected: user not eligible | user=%s | course_id=%s | details=%s",
            request.user.username, course_id, eligibility_details,
        )
        return JsonResponse(
            {
                "success": False,
                "error": "You have not met the eligibility requirements for a certificate yet.",
                "eligibility": eligibility_details,
            },
            status=403,
        )

    response, created = SurveyResponse.objects.update_or_create(
        user=request.user,
        course_id=course_id,
        survey_id=survey_id,
        defaults={"action": action, "metadata": metadata},
    )
    log.info(
        "submit_survey: survey response saved | user=%s | course_id=%s | survey_id=%s | response_id=%s | action=%s | created=%s",
        request.user.username, course_id, survey_id, response.id, response.action, created,
    )

    try:
        generate_certificate(request.user, course_id)
    except Exception:
        log.exception(
            "submit_survey: generate_certificate failed | user=%s | course_id=%s",
            request.user.username, course_id,
        )
        raise
    redirect_url = get_certificate_view_url(request, course_id)
    log.info(
        "submit_survey: certificate generated | user=%s | course_id=%s | redirect_url=%s",
        request.user.username, course_id, redirect_url,
    )

    message = (
        "Your survey response was submitted successfully."
        if action == "submit"
        else "The survey was skipped successfully."
    )

    log.info(
        "submit_survey: returning success response | user=%s | response_id=%s | redirect_url=%s",
        request.user.username, response.id, redirect_url,
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
    Renders the 3-step wizard.
    """
    course_id = request.GET.get("course_id")
    if not course_id:
        return HttpResponse("course_id is required", status=400)

    context = _get_certificate_context(request, course_id)
    
    # Render the WIZARD template
    return render_to_response(CERTIFICATE_WIZARD_TEMPLATE, context, request=request)


@login_required
@require_GET
def certificate_view(request):
    """
    GET /extras/certificate/view/?course_id=...
    Renders the actual final certificate after the survey is completed.
    """
    course_id = request.GET.get("course_id")
    if not course_id:
        return HttpResponse("course_id is required", status=400)

    context = _get_certificate_context(request, course_id)
    
    # Render the FINAL CERTIFICATE template
    return render_to_response(CERTIFICATE_FINAL_TEMPLATE, context, request=request)


@login_required
@require_GET
def certificate_download(request):
    """
    GET /extras/certificate/download/?course_id=...
    Downloads the certificate.
    """
    course_id = request.GET.get("course_id")
    if not course_id:
        return HttpResponse("course_id is required", status=400)

    context = _get_certificate_context(request, course_id)
    
    # Render the final certificate template
    response = render_to_response(CERTIFICATE_FINAL_TEMPLATE, context, request=request)
    
    # FALLBACK: Since PDF generation isn't wired up yet, this forces the browser 
    # to download the rendered HTML file. The learner can open it and use "Print to PDF".
    response['Content-Disposition'] = 'attachment; filename="CMU_Certificate.html"'
    
    return response