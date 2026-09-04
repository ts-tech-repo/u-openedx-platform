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

The row's `action` field represents the CURRENT workflow state.

The row's `metadata` field preserves details for every action:

{
    "name-validate": {
        "created_at": "...",
        ...
    },
    "survey-submit": {
        "created_at": "...",
        ...
    },
    "certificate": {
        "created_at": "...",
        "certificate_context": {
            ...
        }
    }
}
"""

import json
import logging
import time
import weasyprint

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

# Eligibility can be expensive because it may involve course/progress
# queries. Cache it for 5 minutes.
ELIGIBILITY_CACHE_TIMEOUT = CERTIFICTAE_CONFIG.get("eligibility_cache_timeout", 300)

SURVEY_PROGRAM_NAME = CERTIFICTAE_CONFIG.get("survey_program_name", "Agentic AI Program: Building Autonomous Systems for Real-World Applications")

SUPPORT_EMAIL = configuration_helpers.get_value(
    "contact_mailing_address",
    getattr(settings, "CONTACT_EMAIL", {}),
)


# ----------------------------------------------------------------------
# Basic helpers
# ----------------------------------------------------------------------

def _learner_display_name(user):
    """
    Return the learner's display name.
    """
    if hasattr(user, "get_full_name"):
        full_name = user.get_full_name()
    else:
        full_name = f"{user.first_name} {user.last_name}"

    return full_name .strip()


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
    """
    Return the single LearnerSurvey row for the learner/course/survey.

    `.only()` avoids loading unnecessary database fields.
    """

    return (
        LearnerSurvey.objects
        .only(
            "id",
            "action",
            "metadata",
        )
        .filter(
            user=user,
            course_id=course_id,
            survey_id=CERTIFICATE_SURVEY_ID,
        )
        .first()
    )


def _merge_action_metadata(
    existing_metadata,
    action,
    action_metadata=None,
):
    """
    Preserve existing metadata and add/update metadata for the
    specified action.
    """

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

def _get_certificate_context(request, course_id):
    """
    Build JSON-serializable certificate context.
    """

    return {
        "course_id": course_id,
        "survey_id": CERTIFICATE_SURVEY_ID,
        "learner_name": _learner_display_name(request.user),
        "program_name": SURVEY_PROGRAM_NAME,
        "certificate_date": _certificate_date_display(),
        "support_email": SUPPORT_EMAIL,
    }


def _get_certificate_metadata(request, course_id):
    """
    Build certificate metadata for LearnerSurvey.metadata.
    """

    return {
        "created_at": timezone.now().isoformat(),
        "certificate_context": _get_certificate_context(
            request,
            course_id,
        ),
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
        return JsonResponse(
            {"error": "course_id is required"},
            status=400,
        )

    user_email = request.GET.get("email")
    
    try:
        user = User.objects.get(email=user_email) if user_email else request.user
    except User.DoesNotExist:
        return JsonResponse(
            {"error": "user not found"},
            status=400,
        )

    log.info(
        "certificate_status called | "
        "user_id=%s | course_id=%s",
        getattr(user, "id", None),
        course_id,
    )

    # ---------------------------------------------------------------
    # Eligibility
    # ---------------------------------------------------------------

    eligible, eligibility_details = _get_certificate_eligibility (user, course_id)
    log.info(
        "certificate_status eligibility | user=%s | course_id=%s | "
        "eligible=%s | details=%s",
        user.username,
        course_id,
        eligible,
        eligibility_details,
    )

    if not user.is_staff and not eligible:
        log.info(
            "certificate_status: learner not eligible | "
            "user=%s | course_id=%s | is_staff=%s",
            user.username,
            course_id,
            user.is_staff,
        )

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

    # ---------------------------------------------------------------
    # Get workflow state
    # ---------------------------------------------------------------

    learner_survey = _get_current_action(
        user,
        course_id,
    )

    current_action = (
        learner_survey.action
        if learner_survey
        else None
    )

    # ---------------------------------------------------------------
    # Determine state
    # ---------------------------------------------------------------

    name_validated = (
        current_action == LearnerSurvey.ACTION_NAME_VALIDATE
    )

    survey_submitted = (
        current_action == LearnerSurvey.ACTION_SURVEY_SUBMIT
    )

    survey_skipped = (
        current_action == LearnerSurvey.ACTION_SURVEY_SKIP
    )

    completed = (
        current_action == LearnerSurvey.ACTION_CERTIFICATE
    )

    survey_completed = (
        survey_submitted or survey_skipped
    )

    survey_required = (
        name_validated
        and not survey_completed
        and not completed
    )

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

    log.info(
        "certificate_status response | user=%s | course_id=%s | "
        "action=%s | name_validated=%s | survey_submitted=%s | "
        "survey_skipped=%s | completed=%s",
        user.username,
        course_id,
        current_action,
        name_validated,
        survey_submitted,
        survey_skipped,
        completed,
    )

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

    request_start = time.monotonic()

    log.info(
        "=== SURVEY WORKFLOW START === | "
        "user=%s | path=%s | method=%s",
        request.user.username,
        request.path,
        request.method,
    )

    # ---------------------------------------------------------------
    # Parse JSON
    # ---------------------------------------------------------------

    step_start = time.monotonic()

    try:
        data = json.loads(request.body)
    except (TypeError, ValueError):
        log.warning(
            "survey step=JSON_PARSE_FAILED | elapsed=%.4fs",
            time.monotonic() - step_start,
        )

        return JsonResponse(
            {
                "success": False,
                "error": "Invalid JSON",
            },
            status=400,
        )
        
    log.info(
        "survey step=JSON_PARSE | elapsed=%.4fs | payload_keys=%s",
        time.monotonic() - step_start,
        list(data.keys()),
    )

    survey_id = data.get("survey_id")
    course_id = data.get("course_id")
    action = data.get("action")
    request_metadata = data.get("metadata", {})
    user_email = data.get("user_email", "")

    log.info(
        "survey request parsed | "
        "user=%s | email=%s | course_id=%s | survey_id=%s | action=%s",
        request.user.username,
        user_email,
        course_id,
        survey_id,
        action,
    )

    # ---------------------------------------------------------------
    # User lookup
    # ---------------------------------------------------------------

    step_start = time.monotonic()

    try:
        user = User.objects.get(email=user_email) if user_email else request.user
    except User.DoesNotExist:
        log.warning(
            "survey step=USER_LOOKUP_FAILED | "
            "email=%s | elapsed=%.4fs",
            user_email,
            time.monotonic() - step_start,
        )

        return JsonResponse(
            {"error": "user not found"},
            status=400,
        )

    log.info(
        "survey step=USER_LOOKUP | "
        "user_id=%s | username=%s | elapsed=%.4fs",
        user.id,
        user.username,
        time.monotonic() - step_start,
    )

    # ---------------------------------------------------------------
    # Basic validation
    # ---------------------------------------------------------------

    step_start = time.monotonic()

    if not survey_id:
        return JsonResponse(
            {
                "success": False,
                "error": "survey_id is required",
            },
            status=400,
        )

    if survey_id != CERTIFICATE_SURVEY_ID:
        return JsonResponse(
            {
                "success": False,
                "error": "Invalid survey_id",
            },
            status=400,
        )

    if not course_id:
        return JsonResponse(
            {
                "success": False,
                "error": "course_id is required",
            },
            status=400,
        )

    allowed_actions = {
        LearnerSurvey.ACTION_NAME_VALIDATE,
        LearnerSurvey.ACTION_SURVEY_SUBMIT,
        LearnerSurvey.ACTION_SURVEY_SKIP,
    }

    if action not in allowed_actions:
        log.warning(
            "survey step=ACTION_VALIDATION_FAILED | "
            "action=%s | elapsed=%.4fs",
            action,
            time.monotonic() - step_start,
        )

        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Invalid action. Allowed actions are "
                    "name-validate, survey-submit and survey-skip."
                ),
            },
            status=400,
        )

    if not isinstance(request_metadata, dict):
        return JsonResponse(
            {
                "success": False,
                "error": "metadata must be an object",
            },
            status=400,
        )

    log.info(
        "survey step=VALIDATION_COMPLETE | "
        "course_id=%s | requested_action=%s | elapsed=%.4fs",
        course_id,
        action,
        time.monotonic() - step_start,
    )

    # ---------------------------------------------------------------
    # Get current DB state
    # ---------------------------------------------------------------

    step_start = time.monotonic()

    learner_survey = _get_current_action(
        user,
        course_id,
    )

    db_lookup_elapsed = time.monotonic() - step_start

    previous_action = (
        learner_survey.action
        if learner_survey
        else None
    )

    existing_metadata = (
        learner_survey.metadata
        if learner_survey
        and isinstance(learner_survey.metadata, dict)
        else {}
    )

    log.info(
        "survey step=GET_CURRENT_ACTION | "
        "user_id=%s | course_id=%s | "
        "response_id=%s | previous_action=%s | "
        "requested_action=%s | elapsed=%.4fs",
        user.id,
        course_id,
        getattr(learner_survey, "id", None),
        previous_action,
        action,
        db_lookup_elapsed,
    )

    # ---------------------------------------------------------------
    # NAME VALIDATION
    # ---------------------------------------------------------------

    if action == LearnerSurvey.ACTION_NAME_VALIDATE:

        log.info(
            "survey workflow ACTION=name-validate START | "
            "user_id=%s | course_id=%s | previous_action=%s",
            user.id,
            course_id,
            previous_action,
        )

        if previous_action == LearnerSurvey.ACTION_CERTIFICATE:
            log.warning(
                "survey ACTION=name-validate REJECTED | "
                "reason=certificate_already_generated"
            )

            return JsonResponse(
                {
                    "success": False,
                    "error": "Certificate has already been generated.",
                    "current_action": previous_action,
                },
                status=409,
            )

        action_metadata = {
            "name": _learner_display_name(user),
        }

        merged_metadata = _merge_action_metadata(
            existing_metadata=existing_metadata,
            action=LearnerSurvey.ACTION_NAME_VALIDATE,
            action_metadata=action_metadata,
        )

        # -----------------------------------------------------------
        # NAME VALIDATION DB WRITE
        # -----------------------------------------------------------

        step_start = time.monotonic()

        response, created = LearnerSurvey.objects.update_or_create(
            user=user,
            course_id=course_id,
            survey_id=CERTIFICATE_SURVEY_ID,
            defaults={
                "action": LearnerSurvey.ACTION_NAME_VALIDATE,
                "metadata": merged_metadata,
            },
        )

        db_write_elapsed = time.monotonic() - step_start

        log.info(
            "survey step=NAME_VALIDATE_DB_WRITE | "
            "user_id=%s | course_id=%s | "
            "response_id=%s | created=%s | action=%s | "
            "elapsed=%.4fs",
            user.id,
            course_id,
            response.id,
            created,
            response.action,
            db_write_elapsed,
        )

        total_elapsed = time.monotonic() - request_start

        log.info(
            "=== SURVEY WORKFLOW END === | "
            "action=name-validate | "
            "user_id=%s | course_id=%s | "
            "total_elapsed=%.4fs",
            user.id,
            course_id,
            total_elapsed,
        )

        return JsonResponse({
            "success": True,
            "id": response.id,
            "action": response.action,
            "current_action": response.action,
            "name_validated": True,
            "survey_submitted": False,
            "survey_skipped": False,
            "completed": False,
            "metadata": response.metadata,
            "message": "Name validated successfully.",
        })

    # ---------------------------------------------------------------
    # SURVEY SUBMIT / SKIP WORKFLOW VALIDATION
    # ---------------------------------------------------------------

    step_start = time.monotonic()

    if previous_action != LearnerSurvey.ACTION_NAME_VALIDATE and action != previous_action:

        log.warning(
            "survey step=WORKFLOW_STATE_REJECTED | "
            "user_id=%s | course_id=%s | "
            "previous_action=%s | requested_action=%s | "
            "elapsed=%.4fs",
            user.id,
            course_id,
            previous_action,
            action,
            time.monotonic() - step_start,
        )

        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Please verify your name before completing "
                    "the survey."
                ),
                "current_action": previous_action,
            },
            status=409,
        )

    log.info(
        "survey step=WORKFLOW_STATE_VALID | "
        "previous_action=%s | requested_action=%s | elapsed=%.4fs",
        previous_action,
        action,
        time.monotonic() - step_start,
    )

    # ---------------------------------------------------------------
    # Build survey metadata
    # ---------------------------------------------------------------

    step_start = time.monotonic()

    if action == LearnerSurvey.ACTION_SURVEY_SKIP:
        action_metadata = {
            "answers": [],
        }
    else:
        action_metadata = {
            "answers": request_metadata.get("answers", []),
        }

    merged_metadata = _merge_action_metadata(
        existing_metadata=existing_metadata,
        action=action,
        action_metadata=action_metadata,
    )

    log.info(
        "survey step=METADATA_BUILD | "
        "action=%s | answers_count=%s | elapsed=%.4fs",
        action,
        len(action_metadata.get("answers", [])),
        time.monotonic() - step_start,
    )

    # ---------------------------------------------------------------
    # GENERATE CERTIFICATE
    # ---------------------------------------------------------------

    log.info(
        "certificate step=GENERATION START | "
        "user_id=%s | course_id=%s | action=%s",
        user.id,
        course_id,
        action,
    )

    step_start = time.monotonic()

    try:
        _generate_certificate(
            user,
            course_id,
        )
    except Exception as ex:
        generation_elapsed = time.monotonic() - step_start

        log.exception(
            "certificate step=GENERATION FAILED | "
            "user_id=%s | course_id=%s | "
            "action=%s | elapsed=%.4fs | exception=%s",
            user.id,
            course_id,
            action,
            generation_elapsed,
            ex,
        )

        log.info(
            "=== SURVEY WORKFLOW END === | "
            "status=FAILED | stage=certificate_generation | "
            "total_elapsed=%.4fs",
            time.monotonic() - request_start,
        )

        return JsonResponse(
            {
                "success": False,
                "error": "Certificate generation failed.",
            },
            status=500,
        )

    generation_elapsed = time.monotonic() - step_start

    log.info(
        "certificate step=GENERATION COMPLETE | "
        "user_id=%s | course_id=%s | "
        "elapsed=%.4fs",
        user.id,
        course_id,
        generation_elapsed,
    )

    # ---------------------------------------------------------------
    # GET CERTIFICATE METADATA
    # ---------------------------------------------------------------

    log.info(
        "certificate step=GET_METADATA START | "
        "user_id=%s | course_id=%s",
        user.id,
        course_id,
    )

    step_start = time.monotonic()

    certificate_metadata = _get_certificate_metadata(
        request,
        course_id,
    )

    metadata_elapsed = time.monotonic() - step_start

    log.info(
        "certificate step=GET_METADATA COMPLETE | "
        "user_id=%s | course_id=%s | "
        "elapsed=%.4fs | metadata_keys=%s",
        user.id,
        course_id,
        metadata_elapsed,
        list(certificate_metadata.keys()),
    )

    final_metadata = _merge_action_metadata(
        existing_metadata=merged_metadata,
        action=LearnerSurvey.ACTION_CERTIFICATE,
        action_metadata=certificate_metadata,
    )

    # ---------------------------------------------------------------
    # FINAL DB WRITE
    # ---------------------------------------------------------------

    log.info(
        "certificate step=FINAL_DB_WRITE START | "
        "user_id=%s | course_id=%s | "
        "final_action=%s",
        user.id,
        course_id,
        LearnerSurvey.ACTION_CERTIFICATE,
    )

    step_start = time.monotonic()

    response, created = LearnerSurvey.objects.update_or_create(
        user=user,
        course_id=course_id,
        survey_id=CERTIFICATE_SURVEY_ID,
        defaults={
            "action": LearnerSurvey.ACTION_CERTIFICATE,
            "metadata": final_metadata,
        },
    )

    final_db_elapsed = time.monotonic() - step_start

    log.info(
        "certificate step=FINAL_DB_WRITE COMPLETE | "
        "user_id=%s | course_id=%s | "
        "response_id=%s | created=%s | action=%s | "
        "elapsed=%.4fs",
        user.id,
        course_id,
        response.id,
        created,
        response.action,
        final_db_elapsed,
    )

    # ---------------------------------------------------------------
    # COMPLETE
    # ---------------------------------------------------------------

    total_elapsed = time.monotonic() - request_start

    log.info(
        "=== SURVEY WORKFLOW COMPLETE === | "
        "user_id=%s | course_id=%s | "
        "requested_action=%s | final_action=%s | "
        "generation_time=%.4fs | metadata_time=%.4fs | "
        "final_db_time=%.4fs | total_time=%.4fs",
        user.id,
        course_id,
        action,
        response.action,
        generation_elapsed,
        metadata_elapsed,
        final_db_elapsed,
        total_elapsed,
    )

    message = (
        "Your survey response was submitted successfully."
        if action == LearnerSurvey.ACTION_SURVEY_SUBMIT
        else "The survey was skipped successfully."
    )

    return JsonResponse({
        "success": True,
        "id": response.id,
        "action": LearnerSurvey.ACTION_CERTIFICATE,
        "current_action": LearnerSurvey.ACTION_CERTIFICATE,
        "name_validated": True,
        "survey_submitted": (
            action == LearnerSurvey.ACTION_SURVEY_SUBMIT
        ),
        "survey_skipped": (
            action == LearnerSurvey.ACTION_SURVEY_SKIP
        ),
        "completed": True,
        "metadata": response.metadata,
        "message": message,
    })

# ----------------------------------------------------------------------
# Certificate wizard
# ----------------------------------------------------------------------

@login_required
@require_GET
def certificate_generation_view(request):
    """
    GET /extras/certificate/generate/?course_id=...

    Renders the certificate wizard.
    """

    request_start = time.monotonic()

    course_id = request.GET.get("course_id")
    user_email = request.GET.get("email")

    log.info(
        "=== CERTIFICATE VIEW START === | "
        "user=%s | course_id=%s | email=%s",
        request.user.username,
        course_id,
        user_email,
    )

    if not course_id:
        log.warning(
            "certificate_view failed | reason=missing_course_id | "
            "elapsed=%.4fs",
            time.monotonic() - request_start,
        )

        return HttpResponse(
            "course_id is required",
            status=400,
        )

    # ---------------------------------------------------------------
    # User lookup
    # ---------------------------------------------------------------

    step_start = time.monotonic()

    try:
        user = (
            User.objects.get(email=user_email)
            if user_email
            else request.user
        )
    except User.DoesNotExist:

        log.warning(
            "certificate_view USER_LOOKUP_FAILED | "
            "email=%s | elapsed=%.4fs",
            user_email,
            time.monotonic() - step_start,
        )

        return HttpResponse(
            "user not found",
            status=400,
        )

    log.info(
        "certificate_view USER_LOOKUP | "
        "user_id=%s | elapsed=%.4fs",
        user.id,
        time.monotonic() - step_start,
    )

    # ---------------------------------------------------------------
    # Get current action
    # ---------------------------------------------------------------

    step_start = time.monotonic()

    learner_survey = _get_current_action(
        request.user,
        course_id,
    )

    action_elapsed = time.monotonic() - step_start

    current_action = (
        learner_survey.action
        if learner_survey
        else None
    )

    log.info(
        "certificate_view GET_CURRENT_ACTION | "
        "user_id=%s | course_id=%s | "
        "response_id=%s | current_action=%s | "
        "elapsed=%.4fs",
        request.user.id,
        course_id,
        getattr(learner_survey, "id", None),
        current_action,
        action_elapsed,
    )

    # ---------------------------------------------------------------
    # Determine initial step
    # ---------------------------------------------------------------

    step_start = time.monotonic()

    if current_action == LearnerSurvey.ACTION_CERTIFICATE:
        initial_step = 3

    elif current_action in {
        LearnerSurvey.ACTION_NAME_VALIDATE,
        LearnerSurvey.ACTION_SURVEY_SKIP,
    }:
        initial_step = 2

    else:
        initial_step = 1

    log.info(
        "certificate_view INITIAL_STEP | "
        "current_action=%s | initial_step=%s | elapsed=%.4fs",
        current_action,
        initial_step,
        time.monotonic() - step_start,
    )

    # ---------------------------------------------------------------
    # Certificate context
    # ---------------------------------------------------------------

    step_start = time.monotonic()

    context = _get_certificate_context(
        request,
        course_id,
    )

    context_elapsed = time.monotonic() - step_start

    log.info(
        "certificate_view GET_CONTEXT | "
        "course_id=%s | elapsed=%.4fs",
        course_id,
        context_elapsed,
    )

    context.update({
        "status_url": "/extras/certificate/status/",
        "submit_url": "/extras/survey/submit/",
        "download_url": "/extras/certificate/download/",
        "user": user,
        "initial_step": initial_step,
    })

    # ---------------------------------------------------------------
    # Render
    # ---------------------------------------------------------------

    step_start = time.monotonic()

    response = render_to_response(
        CERTIFICATE_WIZARD_TEMPLATE,
        context,
        request=request,
    )

    render_elapsed = time.monotonic() - step_start
    total_elapsed = time.monotonic() - request_start

    log.info(
        "=== CERTIFICATE VIEW COMPLETE === | "
        "user_id=%s | course_id=%s | "
        "current_action=%s | initial_step=%s | "
        "action_lookup=%.4fs | context=%.4fs | "
        "render=%.4fs | total=%.4fs",
        user.id,
        course_id,
        current_action,
        initial_step,
        action_elapsed,
        context_elapsed,
        render_elapsed,
        total_elapsed,
    )

    return response

# ----------------------------------------------------------------------
# Certificate download
# ----------------------------------------------------------------------

@login_required
@require_GET
def certificate_download(request):
    """
    GET /extras/certificate/download/?course_id=...

    Generates and downloads the final certificate PDF.
    """
    course_id = request.GET.get("course_id")
    user_email = request.GET.get("email")

    if not course_id:
        return HttpResponse("course_id is required", status=400)
    try:
        user = User.objects.get(email=user_email) if user_email else request.user
    except User.DoesNotExist:
        return HttpResponse("user not found", status=400)

    learner_survey = _get_current_action(user, course_id)

    current_action = learner_survey.action if learner_survey else None

    log.info(
        "certificate_download called | user=%s | course_id=%s | "
        "response_id=%s | action=%s",
        user.username,
        course_id,
        getattr(learner_survey, "id", None),
        current_action,
    )

    if current_action not in {
        LearnerSurvey.ACTION_CERTIFICATE,
        LearnerSurvey.ACTION_SURVEY_SKIP,
    }:
        return JsonResponse(
            {
                "success": False,
                "error": (
                    "Certificate has not been generated yet."
                ),
            },
            status=403,
        )

    context = _get_certificate_context(request, course_id)

    # ---------------------------------------------------------------
    # Render HTML
    # ---------------------------------------------------------------

    html_string = render_to_string(
        DOWNLOAD_CERTIFICATE_TEMPLATE,
        context,
        request=request,
    )

    # ---------------------------------------------------------------
    # Generate PDF
    # ---------------------------------------------------------------

    try:
        pdf_file = weasyprint.HTML(
            string=html_string,
            base_url=request.build_absolute_uri(),
        ).write_pdf()

    except Exception as ex:  # pylint: disable=broad-except
        log.exception(
            "PDF generation failed | "
            "user_id=%s | course_id=%s | error=%s",
            user.id,
            course_id,
            ex,
        )

        return HttpResponse(
            "Failed to generate PDF certificate.",
            status=500,
        )

    # ---------------------------------------------------------------
    # Return PDF
    # ---------------------------------------------------------------

    response = HttpResponse(
        pdf_file,
        content_type="application/pdf",
    )

    filename = (
        f"CERT-{request.user.username}.pdf"
    )

    response[
        "Content-Disposition"
    ] = f'attachment; filename="{filename}"'

    return response