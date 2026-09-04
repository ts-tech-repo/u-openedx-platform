"""
API + page views for custom_lms's survey-then-certificate flow.

Workflow:

    Course Progress page
        -> GET certificate_status
        -> certificate_generation_view
        -> STEP 1: POST action=name-validate
        -> STEP 2: POST action=survey-submit / survey-skip
        -> certificate generated
        -> DB action updated to certificate
        -> STEP 3 / certificate_view

Only one LearnerSurvey row exists for a learner/course/survey.
"""

import json
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from common.djangoapps.edxmako.shortcuts import (
    render_to_response,
    render_to_string,
)

from custom_lms.models.learner_survey import LearnerSurvey
from custom_lms.views.eligibility import is_eligible_for_certificate

from openedx.core.djangoapps.site_configuration import (
    helpers as configuration_helpers,
)

User = get_user_model()
log = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------

CERTIFICTAE_CONFIG = configuration_helpers.get_value(
    "CERTIFICATE_CONFIG",
    getattr(settings, "CERTIFICATE_CONFIG", {}),
)

CERTIFICATE_SURVEY_ID = CERTIFICTAE_CONFIG.get("survey_id", "course-completion-survey")

CERTIFICATE_WIZARD_TEMPLATE = CERTIFICTAE_CONFIG.get("certificate_wizard_template", "cmu_certificate_wizard.html")
DOWNLOAD_CERTIFICATE_TEMPLATE = CERTIFICTAE_CONFIG.get("download_certificate_template", "cmu_certificate.html")
ELIGIBILITY_CACHE_TIMEOUT = CERTIFICTAE_CONFIG.get("eligibility_cache_timeout", 300)

SURVEY_PROGRAM_NAME = CERTIFICTAE_CONFIG.get("survey_program_name", "Agentic AI Program: Building Autonomous Systems for Real-World Applications")

SUPPORT_EMAIL = configuration_helpers.get_value(
    "contact_mailing_address",
    getattr(settings, "CONTACT_EMAIL", {}),
)


# ----------------------------------------------------------------------
# Basic helpers
# ----------------------------------------------------------------------

def _resolve_user(request, user_email):
    """
    Resolve the user object, avoiding unnecessary DB queries 
    if the email matches the already authenticated request.user.
    """
    if user_email and user_email != request.user.email:
        try:
            return User.objects.get(email=user_email)
        except User.DoesNotExist:
            return None
    return request.user


def _learner_display_name(user):
    """
    Return the learner's display name.
    """
    if hasattr(user, "get_full_name"):
        full_name = user.get_full_name()
    else:
        full_name = f"{user.first_name} {user.last_name}"
    return full_name.strip()


def _certificate_date_display():
    """
    Return certificate date in display format.
    """
    return timezone.now().strftime("%B %-d, %Y")


# ----------------------------------------------------------------------
# Eligibility
# ----------------------------------------------------------------------

def _eligibility_cache_key(user, course_id):
    """
    Build a unique cache key for learner/course eligibility.
    """
    return f"certificate-eligibility:{user.id}:{course_id}"


def _get_certificate_eligibility(user, course_id):
    """
    Return certificate eligibility.

    The actual eligibility calculation is cached because it can be
    expensive and is called by multiple endpoints in the workflow.
    """

    cache_key = _eligibility_cache_key(user, course_id)

    cached_result = cache.get(cache_key)

    if cached_result is not None:
        return cached_result

    start_time = timezone.now()

    result = is_eligible_for_certificate(
        user,
        course_id,
    )

    elapsed = (
        timezone.now() - start_time
    ).total_seconds()

    log.info(
        "certificate eligibility calculated | "
        "user_id=%s | course_id=%s | eligible=%s | elapsed=%.3fs",
        getattr(user, "id", None),
        course_id,
        result[0],
        elapsed,
    )

    cache.set(
        cache_key,
        result,
        ELIGIBILITY_CACHE_TIMEOUT,
    )

    return result


def _clear_certificate_eligibility_cache(user, course_id):
    """
    Clear cached eligibility.

    Call this if course progress/grades are changed and eligibility
    needs to be recalculated immediately.
    """
    cache.delete(
        _eligibility_cache_key(user, course_id)
    )


# ----------------------------------------------------------------------
# LearnerSurvey helpers
# ----------------------------------------------------------------------

def _get_current_action(user, course_id):
    """Return the single LearnerSurvey row for the learner/course/survey."""
    return (
        LearnerSurvey.objects
        .only("id", "action", "metadata")
        .filter(
            user=user,
            course_id=course_id,
            survey_id=CERTIFICATE_SURVEY_ID,
        )
        .first()
    )


def _merge_action_metadata(existing_metadata, action, action_metadata=None):
    """Preserve existing metadata and add/update metadata for the specified action."""
    if not isinstance(existing_metadata, dict):
        existing_metadata = {}

    merged_metadata = dict(existing_metadata)

    current_action_metadata = merged_metadata.get(action, {})

    if not isinstance(current_action_metadata, dict):
        current_action_metadata = {}

    new_action_metadata = dict(current_action_metadata)

    if isinstance(action_metadata, dict):
        new_action_metadata.update(action_metadata)

    # Always maintain created_at for this action.
    if not new_action_metadata.get("created_at"):
        new_action_metadata["created_at"] = timezone.now().isoformat()

    merged_metadata[action] = new_action_metadata

    return merged_metadata


# ----------------------------------------------------------------------
# Certificate helpers
# ----------------------------------------------------------------------

def _get_certificate_context(user, course_id):
    """
    Build JSON-serializable certificate context.
    """

    return {
        "course_id": course_id,
        "survey_id": CERTIFICATE_SURVEY_ID,
        "learner_name": _learner_display_name(user),
        "program_name": SURVEY_PROGRAM_NAME,
        "certificate_date": _certificate_date_display(),
        "support_email": SUPPORT_EMAIL,
    }


def _get_certificate_metadata(user, course_id):
    """
    Build certificate metadata for LearnerSurvey.metadata.
    """

    return {
        "created_at": timezone.now().isoformat(),
        "certificate_context": _get_certificate_context(user, course_id),
    }


def _generate_certificate(user, course_id):
    """
    Certificate is dynamically rendered by the certificate template.
    """

    log.info(
        "certificate generation triggered | user=%s | user_id=%s | course_id=%s",
        getattr(user, "username", "unknown"),
        getattr(user, "id", None),
        course_id,
    )

    return True


# ----------------------------------------------------------------------
# Certificate status
# ----------------------------------------------------------------------

@login_required
@require_GET
def certificate_status(request):
    """
    GET /extras/certificate/status/?course_id=...

    Returns the current certificate workflow state.
    """

    course_id = request.GET.get("course_id")

    if not course_id:
        return JsonResponse({"error": "course_id is required"}, status=400)

    user_email = request.GET.get("email")
    user = _resolve_user(request, user_email)
    
    if not user:
        return JsonResponse({"error": "user not found"}, status=400)

    log.info("certificate_status called | user_id=%s | course_id=%s", getattr(user, "id", None), course_id)
    # ---------------------------------------------------------------
    # Eligibility
    # ---------------------------------------------------------------
    
    eligible, eligibility_details = _get_certificate_eligibility(user, course_id)
    
    if not user.is_staff and not eligible:
        return JsonResponse({
            "eligible": False,
            "eligibility": eligibility_details,
            "survey_id": CERTIFICATE_SURVEY_ID,
            "name_validated": False,
            "survey_submitted": False,
            "survey_skipped": False,
            "completed": False,
            "current_action": None,
            "survey_required": False,
        })

    learner_survey = _get_current_action(user, course_id)
    current_action = learner_survey.action if learner_survey else None

    name_validated = (current_action == LearnerSurvey.ACTION_NAME_VALIDATE)
    survey_submitted = (current_action == LearnerSurvey.ACTION_SURVEY_SUBMIT)
    survey_skipped = (current_action == LearnerSurvey.ACTION_SURVEY_SKIP)
    completed = (current_action == LearnerSurvey.ACTION_CERTIFICATE)
    
    survey_required = name_validated and not (survey_submitted or survey_skipped) and not completed

    response_payload = {
        "eligible": True,
        "eligibility": eligibility_details,
        "survey_id": CERTIFICATE_SURVEY_ID,
        "current_action": current_action,
        "name_validated": name_validated,
        "survey_submitted": survey_submitted,
        "survey_skipped": survey_skipped,
        "completed": completed,
        "survey_required": survey_required,
        "learner_name": _learner_display_name(user),
        "program_name": SURVEY_PROGRAM_NAME,
        "certificate_date": _certificate_date_display(),
    }

    return JsonResponse(response_payload)


# ----------------------------------------------------------------------
# Survey submit
# ----------------------------------------------------------------------

@login_required
@require_POST
def submit_survey(request):
    """
    POST /extras/survey/submit/

    Supported actions:

        name-validate
        survey-submit
        survey-skip

    Tracks detailed timing for every workflow step.
    """
    log.info("=== SURVEY WORKFLOW START === | user=%s | path=%s | method=%s", request.user.username, request.path, request.method)

    try:
        data = json.loads(request.body)
    except (TypeError, ValueError):
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    survey_id = data.get("survey_id")
    course_id = data.get("course_id")
    action = data.get("action")
    request_metadata = data.get("metadata", {})
    user_email = data.get("user_email", "")

    user = _resolve_user(request, user_email)
    if not user:
        return JsonResponse({"error": "user not found"}, status=400)

    if not survey_id or survey_id != CERTIFICATE_SURVEY_ID:
        return JsonResponse({"success": False, "error": "Invalid survey_id"}, status=400)

    if not course_id:
        return JsonResponse({"success": False, "error": "course_id is required"}, status=400)

    allowed_actions = {
        LearnerSurvey.ACTION_NAME_VALIDATE,
        LearnerSurvey.ACTION_SURVEY_SUBMIT,
        LearnerSurvey.ACTION_SURVEY_SKIP,
    }

    if action not in allowed_actions:
        return JsonResponse(
            {"success": False, "error": "Invalid action. Allowed actions are name-validate, survey-submit and survey-skip."},
            status=400,
        )

    if not isinstance(request_metadata, dict):
        return JsonResponse({"success": False, "error": "metadata must be an object"}, status=400)

    learner_survey = _get_current_action(user, course_id)
    previous_action = learner_survey.action if learner_survey else None
    existing_metadata = learner_survey.metadata if (learner_survey and isinstance(learner_survey.metadata, dict)) else {}

    # ---------------------------------------------------------------
    # NAME VALIDATION
    # ---------------------------------------------------------------

    if action == LearnerSurvey.ACTION_NAME_VALIDATE:
        if previous_action == LearnerSurvey.ACTION_CERTIFICATE:
            return JsonResponse(
                {"success": False, "error": "Certificate has already been generated.", "current_action": previous_action},
                status=409,
            )

        merged_metadata = _merge_action_metadata(
            existing_metadata=existing_metadata,
            action=LearnerSurvey.ACTION_NAME_VALIDATE,
            action_metadata={"name": _learner_display_name(user)},
        )

        if learner_survey:
            learner_survey.action = LearnerSurvey.ACTION_NAME_VALIDATE
            learner_survey.metadata = merged_metadata
            learner_survey.save(update_fields=['action', 'metadata'])
            response, created = learner_survey, False
        else:
            response = LearnerSurvey.objects.create(
                user=user, course_id=course_id, survey_id=CERTIFICATE_SURVEY_ID,
                action=LearnerSurvey.ACTION_NAME_VALIDATE, metadata=merged_metadata,
            )
            created = True

        return JsonResponse({
            "success": True, "id": response.id, "action": response.action, "current_action": response.action,
            "name_validated": True, "survey_submitted": False, "survey_skipped": False, "completed": False,
            "metadata": response.metadata, "message": "Name validated successfully.",
        })

    # ---------------------------------------------------------------
    # SURVEY SUBMIT / SKIP WORKFLOW VALIDATION
    # ---------------------------------------------------------------
    if previous_action != LearnerSurvey.ACTION_NAME_VALIDATE and action != previous_action:
        return JsonResponse(
            {"success": False, "error": "Please verify your name before completing the survey.", "current_action": previous_action},
            status=409,
        )

    action_metadata = {"answers": []} if action == LearnerSurvey.ACTION_SURVEY_SKIP else {"answers": request_metadata.get("answers", [])}
    
    merged_metadata = _merge_action_metadata(
        existing_metadata=existing_metadata,
        action=action,
        action_metadata=action_metadata,
    )

    # ---------------------------------------------------------------
    # GENERATE CERTIFICATE
    # ---------------------------------------------------------------
    try:
        _generate_certificate(user, course_id)
    except Exception as ex:
        log.exception("certificate step=GENERATION FAILED | user_id=%s | course_id=%s | exception=%s", user.id, course_id, ex)
        return JsonResponse({"success": False, "error": "Certificate generation failed."}, status=500)

    certificate_metadata = _get_certificate_metadata(user, course_id)
    final_metadata = _merge_action_metadata(
        existing_metadata=merged_metadata,
        action=LearnerSurvey.ACTION_CERTIFICATE,
        action_metadata=certificate_metadata,
    )

    final_action = LearnerSurvey.ACTION_SURVEY_SKIP if action == LearnerSurvey.ACTION_SURVEY_SKIP else LearnerSurvey.ACTION_CERTIFICATE

    # ---------------------------------------------------------------
    # FINAL DB WRITE (Optimized to avoid redundant SELECT from update_or_create)
    # ---------------------------------------------------------------
    if learner_survey:
        learner_survey.action = final_action
        learner_survey.metadata = final_metadata
        learner_survey.save(update_fields=['action', 'metadata'])
        response, created = learner_survey, False
    else:
        response = LearnerSurvey.objects.create(
            user=user, course_id=course_id, survey_id=CERTIFICATE_SURVEY_ID,
            action=final_action, metadata=final_metadata,
        )
        created = True

    message = "Your survey response was submitted successfully." if action == LearnerSurvey.ACTION_SURVEY_SUBMIT else "The survey was skipped successfully."

    return JsonResponse({
        "success": True, "id": response.id, "action": final_action, "current_action": final_action,
        "name_validated": True, "survey_submitted": action == LearnerSurvey.ACTION_SURVEY_SUBMIT,
        "survey_skipped": action == LearnerSurvey.ACTION_SURVEY_SKIP, "completed": final_action == LearnerSurvey.ACTION_CERTIFICATE,
        "metadata": response.metadata, "message": message,
    })


# ----------------------------------------------------------------------
# Certificate wizard
# ----------------------------------------------------------------------

@login_required
@require_GET
def certificate_generation_view(request):
    
    course_id = request.GET.get("course_id")
    user_email = request.GET.get("email")

    if not course_id:
        return HttpResponse("course_id is required", status=400)

    user = _resolve_user(request, user_email)
    if not user:
        return HttpResponse("user not found", status=400)

    learner_survey = _get_current_action(user, course_id)
    current_action = learner_survey.action if learner_survey else None

    # Optimized: Direct evaluation without redundant dictionary lookups
    if current_action == LearnerSurvey.ACTION_CERTIFICATE:
        initial_step = 3
    elif current_action == LearnerSurvey.ACTION_SURVEY_SKIP:
        initial_step = 2
    else:
        initial_step = 1

    context = _get_certificate_context(user, course_id)
    context.update({
        "status_url": "/extras/certificate/status/",
        "submit_url": "/extras/survey/submit/",
        "download_url": "/extras/certificate/download/",
        "user": user,
        "initial_step": initial_step,
    })

    response = render_to_response(CERTIFICATE_WIZARD_TEMPLATE, context, request=request)
    return response


# ----------------------------------------------------------------------
# Certificate download
# ----------------------------------------------------------------------

@login_required
@require_GET
def certificate_download(request):
    course_id = request.GET.get("course_id")
    user_email = request.GET.get("email")

    if not course_id:
        return HttpResponse("course_id is required", status=400)
        
    user = _resolve_user(request, user_email)
    if not user:
        return HttpResponse("user not found", status=400)

    learner_survey = _get_current_action(user, course_id)
    current_action = learner_survey.action if learner_survey else None

    if current_action not in {LearnerSurvey.ACTION_CERTIFICATE, LearnerSurvey.ACTION_SURVEY_SKIP}:
        return JsonResponse({"success": False, "error": "Certificate has not been generated yet."}, status=403)

    context = _get_certificate_context(user, course_id)
    html_string = render_to_string(DOWNLOAD_CERTIFICATE_TEMPLATE, context, request=request)

    try:
        import weasyprint
        pdf_file = weasyprint.HTML(string=html_string, base_url=request.build_absolute_uri()).write_pdf()
    except Exception as ex:
        log.exception("PDF generation failed | user_id=%s | course_id=%s | error=%s", user.id, course_id, ex)
        return HttpResponse("Failed to generate PDF certificate.", status=500)

    response = HttpResponse(pdf_file, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="CERT-{user.username}.pdf"'
    return response