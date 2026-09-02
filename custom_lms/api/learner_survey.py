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

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from common.djangoapps.edxmako.shortcuts import render_to_response
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from custom_lms.models.learner_survey import LearnerSurvey
from custom_lms.views.eligibility import is_eligible_for_certificate
from openedx.core.djangoapps.site_configuration import (
    helpers as configuration_helpers,
)


log = logging.getLogger(__name__)


CERTIFICATE_SURVEY_ID = "course-completion-survey"

SURVEY_PROGRAM_NAME = configuration_helpers.get_value(
    "SURVEY_PROGRAM_NAME",
    "Agentic AI Program: Building Autonomous Systems for Real-World Applications",
)

SUPPORT_EMAIL = configuration_helpers.get_value(
    "contact_mailing_address",
    settings.CONTACT_EMAIL,
)

CERTIFICATE_WIZARD_TEMPLATE = "cmu_learner_certificate.html"
CERTIFICATE_FINAL_TEMPLATE = "cmu_certificate.html"


def _learner_display_name(user):
    full_name = (
        user.get_full_name()
        if hasattr(user, "get_full_name")
        else f"{user.first_name} {user.last_name}"
    )

    return (full_name or "").strip()


def _certificate_date_display():
    return timezone.now().strftime("%B %-d, %Y")


def _get_current_action(user, course_id):
    """
    Returns the single LearnerSurvey row for the learner/course/survey.
    """
    return LearnerSurvey.objects.filter(
        user=user,
        course_id=course_id,
        survey_id=CERTIFICATE_SURVEY_ID,
    ).first()


def _merge_action_metadata(
    existing_metadata,
    action,
    action_metadata=None,
):
    """
    Preserve existing metadata and add/update metadata for the
    specified action.

    Existing action metadata is NOT removed.

    Example:

        existing:
        {
            "name-validate": {...}
        }

        after survey-submit:
        {
            "name-validate": {...},
            "survey-submit": {...}
        }
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


def _get_certificate_context(request, course_id):
    """
    Build the certificate context.

    This context is also safe to store in JSON metadata because it
    contains only JSON-serializable values.
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
    Return the certificate creation metadata.

    This is intentionally separate from the Django template context
    because request/user objects must not be stored in JSONField.
    """

    certificate_context = _get_certificate_context(
        request,
        course_id,
    )

    return {
        "created_at": timezone.now().isoformat(),
        "certificate_context": certificate_context,
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

@login_required
@require_GET
def certificate_status(request):
    """
    GET /extras/certificate/status/?course_id=...

    Returns the current workflow state.

    DB action:

        None
            -> Step 1

        name-validate
            -> Step 2

        survey-submit / survey-skip
            -> transitional state

        certificate
            -> Step 3
    """

    course_id = request.GET.get("course_id")

    user = request.user
    username = getattr(user, "username", None)
    user_id = getattr(user, "id", None)

    log.info(
        "certificate_status called | user=%s | user_id=%s | "
        "is_staff=%s | course_id=%s",
        username,
        user_id,
        getattr(user, "is_staff", False),
        course_id,
    )

    if not course_id:
        log.warning(
            "certificate_status rejected: missing course_id | "
            "user=%s | user_id=%s",
            username,
            user_id,
        )

        return JsonResponse(
            {"error": "course_id is required"},
            status=400,
        )

    # ---------------------------------------------------------------
    # Eligibility
    # ---------------------------------------------------------------

    eligible, eligibility_details = is_eligible_for_certificate(
        user,
        course_id,
    )

    log.info(
        "certificate_status eligibility | user=%s | course_id=%s | "
        "eligible=%s | details=%s",
        username,
        course_id,
        eligible,
        eligibility_details,
    )

    if not user.is_staff and not eligible:
        log.info(
            "certificate_status: learner not eligible | "
            "user=%s | course_id=%s | is_staff=%s",
            username,
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
    # Get the ONE workflow row
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

    metadata = (
        learner_survey.metadata
        if learner_survey and isinstance(learner_survey.metadata, dict)
        else {}
    )

    log.info(
        "certificate_status survey state | user=%s | course_id=%s | "
        "response_id=%s | action=%s | metadata_keys=%s",
        username,
        course_id,
        getattr(learner_survey, "id", None),
        current_action,
        list(metadata.keys()),
    )

    # ---------------------------------------------------------------
    # Current state
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
        username,
        course_id,
        current_action,
        name_validated,
        survey_submitted,
        survey_skipped,
        completed,
    )

    return JsonResponse(response_payload)


@login_required
@require_POST
def submit_survey(request):
    """
    POST /extras/survey/submit/

    Supported client actions:

        name-validate
        survey-submit
        survey-skip

    `certificate` can NEVER be supplied by the client.

    The same DB row is updated throughout the workflow.
    """

    username = getattr(request.user, "username", None)
    user_id = getattr(request.user, "id", None)

    log.info(
        "submit_survey called | user=%s | user_id=%s",
        username,
        user_id,
    )

    # ---------------------------------------------------------------
    # Parse JSON
    # ---------------------------------------------------------------

    try:
        data = json.loads(request.body)
    except (TypeError, ValueError):
        log.warning(
            "submit_survey invalid JSON | user=%s",
            username,
        )

        return JsonResponse(
            {
                "success": False,
                "error": "Invalid JSON",
            },
            status=400,
        )

    survey_id = data.get("survey_id")
    course_id = data.get("course_id")
    action = data.get("action")
    request_metadata = data.get("metadata", {})

    log.info(
        "submit_survey payload | user=%s | survey_id=%s | "
        "course_id=%s | action=%s | metadata_keys=%s",
        username,
        survey_id,
        course_id,
        action,
        (
            list(request_metadata.keys())
            if isinstance(request_metadata, dict)
            else type(request_metadata).__name__
        ),
    )

    # ---------------------------------------------------------------
    # Basic validation
    # ---------------------------------------------------------------

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
            "submit_survey invalid action | user=%s | action=%s",
            username,
            action,
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

    # ---------------------------------------------------------------
    # Eligibility
    # ---------------------------------------------------------------

    eligible, eligibility_details = is_eligible_for_certificate(
        request.user,
        course_id,
    )

    log.info(
        "submit_survey eligibility | user=%s | course_id=%s | "
        "eligible=%s | details=%s",
        username,
        course_id,
        eligible,
        eligibility_details,
    )

    if not request.user.is_staff and not eligible:
        log.warning(
            "submit_survey rejected: user not eligible | "
            "user=%s | course_id=%s",
            username,
            course_id,
        )

        return JsonResponse(
            {
                "success": False,
                "error": (
                    "You have not met the eligibility requirements "
                    "for a certificate yet."
                ),
                "eligibility": eligibility_details,
            },
            status=403,
        )

    # ---------------------------------------------------------------
    # Get existing SINGLE workflow row
    # ---------------------------------------------------------------

    learner_survey = _get_current_action(
        request.user,
        course_id,
    )

    previous_action = (
        learner_survey.action
        if learner_survey
        else None
    )

    existing_metadata = (
        learner_survey.metadata
        if learner_survey and isinstance(learner_survey.metadata, dict)
        else {}
    )

    log.info(
        "submit_survey previous state | user=%s | course_id=%s | "
        "response_id=%s | previous_action=%s | requested_action=%s | "
        "existing_metadata_keys=%s",
        username,
        course_id,
        getattr(learner_survey, "id", None),
        previous_action,
        action,
        list(existing_metadata.keys()),
    )

    # ---------------------------------------------------------------
    # NAME VALIDATION
    # ---------------------------------------------------------------

    if action == LearnerSurvey.ACTION_NAME_VALIDATE:

        if previous_action == LearnerSurvey.ACTION_CERTIFICATE:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Certificate has already been generated.",
                    "current_action": previous_action,
                },
                status=409,
            )

        # Do not trust client-provided name.
        action_metadata = {
            "name": _learner_display_name(request.user),
        }

        merged_metadata = _merge_action_metadata(
            existing_metadata=existing_metadata,
            action=LearnerSurvey.ACTION_NAME_VALIDATE,
            action_metadata=action_metadata,
        )

        response, created = LearnerSurvey.objects.update_or_create(
            user=request.user,
            course_id=course_id,
            survey_id=CERTIFICATE_SURVEY_ID,
            defaults={
                "action": LearnerSurvey.ACTION_NAME_VALIDATE,
                "metadata": merged_metadata,
            },
        )

        log.info(
            "name validation saved | user=%s | course_id=%s | "
            "response_id=%s | created=%s | action=%s | metadata_keys=%s",
            username,
            course_id,
            response.id,
            created,
            response.action,
            list(response.metadata.keys()),
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
    # SURVEY SUBMIT / SKIP
    # ---------------------------------------------------------------

    if previous_action != LearnerSurvey.ACTION_NAME_VALIDATE:
        log.warning(
            "survey action rejected due to invalid workflow state | "
            "user=%s | course_id=%s | previous_action=%s | action=%s",
            username,
            course_id,
            previous_action,
            action,
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

    # ---------------------------------------------------------------
    # Build survey metadata
    # ---------------------------------------------------------------

    if action == LearnerSurvey.ACTION_SURVEY_SKIP:
        action_metadata = {
            "answers": [],
        }

    else:
        action_metadata = {
            "answers": request_metadata.get("answers", []),
        }

    # Add survey action metadata WITHOUT deleting name-validate.
    merged_metadata = _merge_action_metadata(
        existing_metadata=existing_metadata,
        action=action,
        action_metadata=action_metadata,
    )

    # ---------------------------------------------------------------
    # Save survey action
    #
    # SAME DB ROW
    # ---------------------------------------------------------------

    response, created = LearnerSurvey.objects.update_or_create(
        user=request.user,
        course_id=course_id,
        survey_id=CERTIFICATE_SURVEY_ID,
        defaults={
            "action": action,
            "metadata": merged_metadata,
        },
    )

    log.info(
        "survey action saved | user=%s | course_id=%s | "
        "response_id=%s | action=%s | created=%s | metadata_keys=%s",
        username,
        course_id,
        response.id,
        action,
        created,
        list(response.metadata.keys()),
    )

    # ---------------------------------------------------------------
    # Generate certificate
    # ---------------------------------------------------------------

    try:
        _generate_certificate(
            request.user,
            course_id,
        )

    except Exception:
        log.exception(
            "certificate generation failed | user=%s | course_id=%s | "
            "response_id=%s | action=%s",
            username,
            course_id,
            response.id,
            action,
        )
        raise

    # ---------------------------------------------------------------
    # Add certificate metadata
    #
    # IMPORTANT:
    # Existing metadata is preserved.
    #
    # {
    #     "name-validate": {...},
    #     "survey-submit": {...},
    #     "certificate": {...}
    # }
    # ---------------------------------------------------------------

    certificate_metadata = _get_certificate_metadata(
        request,
        course_id,
    )

    final_metadata = _merge_action_metadata(
        existing_metadata=response.metadata,
        action=LearnerSurvey.ACTION_CERTIFICATE,
        action_metadata=certificate_metadata,
    )

    # ---------------------------------------------------------------
    # IMPORTANT:
    # Update the SAME row to certificate.
    # ---------------------------------------------------------------

    previous_action_before_certificate = response.action

    response.action = LearnerSurvey.ACTION_CERTIFICATE
    response.metadata = final_metadata

    response.save(
        update_fields=[
            "action",
            "metadata",
            "updated_at",
        ]
    )

    log.info(
        "certificate action saved | user=%s | course_id=%s | "
        "response_id=%s | previous_action=%s | action=%s | "
        "metadata_keys=%s",
        username,
        course_id,
        response.id,
        previous_action_before_certificate,
        response.action,
        list(response.metadata.keys()),
    )

    message = (
        "Your survey response was submitted successfully."
        if action == LearnerSurvey.ACTION_SURVEY_SUBMIT
        else "The survey was skipped successfully."
    )

    return JsonResponse({
        "success": True,
        "id": response.id,

        # Final DB state.
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


@login_required
@require_GET
def certificate_generation_view(request):
    """
    GET /extras/certificate/generate/?course_id=...

    Renders the certificate wizard.
    """

    course_id = request.GET.get("course_id")

    if not course_id:
        return HttpResponse(
            "course_id is required",
            status=400,
        )

    log.info(
        "certificate_generation_view | user=%s | course_id=%s",
        request.user.username,
        course_id,
    )

    eligible, eligibility_details = is_eligible_for_certificate(
        request.user,
        course_id,
    )

    if not request.user.is_staff and not eligible:
        log.warning(
            "certificate_generation_view denied | user=%s | "
            "course_id=%s | details=%s",
            request.user.username,
            course_id,
            eligibility_details,
        )

        return HttpResponse(
            "You are not eligible for a certificate.",
            status=403,
        )

    context = _get_certificate_context(
        request,
        course_id,
    )

    context.update({
        "status_url": "/extras/certificate/status/",
        "submit_url": "/extras/survey/submit/",
        "download_url": "/extras/certificate/download/",
        "user": request.user,
    })

    return render_to_response(
        CERTIFICATE_WIZARD_TEMPLATE,
        context,
        request=request,
    )


@login_required
@require_GET
def certificate_download(request):
    """
    GET /extras/certificate/download/?course_id=...

    Downloads the certificate only when current action is
    `certificate`.
    """

    course_id = request.GET.get("course_id")

    if not course_id:
        return HttpResponse(
            "course_id is required",
            status=400,
        )

    learner_survey = _get_current_action(
        request.user,
        course_id,
    )

    current_action = (
        learner_survey.action
        if learner_survey
        else None
    )

    log.info(
        "certificate_download called | user=%s | course_id=%s | "
        "response_id=%s | action=%s",
        request.user.username,
        course_id,
        getattr(learner_survey, "id", None),
        current_action,
    )

    if current_action != LearnerSurvey.ACTION_CERTIFICATE:
        log.warning(
            "certificate_download denied | user=%s | "
            "course_id=%s | action=%s",
            request.user.username,
            course_id,
            current_action,
        )

        return JsonResponse(
            {
                "success": False,
                "error": "Certificate has not been generated yet.",
            },
            status=403,
        )

    context = _get_certificate_context(
        request,
        course_id,
    )

    context.update({
        "status_url": "/extras/certificate/status/",
        "submit_url": "/extras/survey/submit/",
        "download_url": "/extras/certificate/download/",
        "user": request.user,
    })

    response = render_to_response(
        CERTIFICATE_FINAL_TEMPLATE,
        context,
        request=request,
    )

    filename = f"CERT-{request.user.username}.html"
    response["Content-Disposition"] = (
        f"attachment; filename={filename}"
    )

    return response