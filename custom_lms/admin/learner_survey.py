

from django.contrib import admin
from django.contrib.auth import get_user_model

from ..models.learner_survey import LearnerSurvey

@admin.register(LearnerSurvey)
class LearnerSurveyAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "learner",
        "course_id",
        "survey_id",
        "action",
        "created_at",
    )
    list_filter = ("action", "survey_id", "created_at")
    search_fields = (
        "user__username",
        "user__email",
        "course_id",
        "survey_id",
    )
    readonly_fields = (
        "user",
        "course_id",
        "survey_id",
        "action",
        "metadata",
        "created_at",
        "updated_at",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)

    def learner(self, obj):
        return f"{obj.user.username} ({obj.user.email})"
    learner.short_description = "Learner"
    learner.admin_order_field = "user__username"

    def has_add_permission(self, request):
        # Responses are only ever created via the API, never by hand.
        return False

    def has_change_permission(self, request, obj=None):
        # Read-only in the admin — this is a reporting view.
        return False