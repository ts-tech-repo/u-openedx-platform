"""
Models for the custom_lms survey / certificate-eligibility app.
"""

from django.conf import settings
from django.db import models

try:
    # Standard Open edX way of storing a CourseKey as a model field.
    # Falls back to a plain CharField if opaque_keys isn't importable
    # (e.g. while unit testing this app outside of edx-platform).
    from opaque_keys.edx.django.models import CourseKeyField
    COURSE_ID_FIELD = CourseKeyField(max_length=255, db_index=True)
except ImportError:  # pragma: no cover
    COURSE_ID_FIELD = models.CharField(max_length=255, db_index=True)


class SurveyResponse(models.Model):
    """
    One row per (user, course, survey). `action` records whether the
    learner submitted answers or explicitly skipped; `metadata` holds
    the answers (or anything else you want to attach) as JSON.

    metadata shape when action == "submit":

        {
            "answers": [
                {"question": "1. The program helped me...", "answer": "Agree"},
                {"question": "2. The action plans...",      "answer": "Neutral"},
                ...
            ]
        }

    metadata is `{}` when action == "skip".
    """

    ACTION_SUBMIT = "submit"
    ACTION_SKIP = "skip"
    ACTION_CHOICES = (
        (ACTION_SUBMIT, "Submitted"),
        (ACTION_SKIP, "Skipped"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="survey_responses",
    )
    course_id = COURSE_ID_FIELD
    survey_id = models.CharField(max_length=255, db_index=True)

    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "custom_lms"
        # One response per learner, per survey, per course. Resubmitting
        # updates the existing row instead of creating a duplicate.
        unique_together = ("user", "course_id", "survey_id")
        indexes = [
            models.Index(fields=["user", "course_id", "survey_id"]),
        ]

    @property
    def skipped(self):
        return self.action == self.ACTION_SKIP

    @property
    def answers(self):
        return (self.metadata or {}).get("answers", [])

    def __str__(self):
        return (
            f"SurveyResponse(user_id={self.user_id}, course_id={self.course_id}, "
            f"survey_id={self.survey_id}, action={self.action})"
        )