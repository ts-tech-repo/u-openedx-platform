

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html


from ..models.learner_survey import LearnerSurvey
# --------------------------------------------------------------------------- #
#  Common actions                                                              #
# --------------------------------------------------------------------------- #

def record_actions(obj):
    update_url = reverse(
        f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change",
        args=[obj.pk],
    )
    delete_url = reverse(
        f"admin:{obj._meta.app_label}_{obj._meta.model_name}_delete",
        args=[obj.pk],
    )

    return format_html(
        '<a href="{}">Update</a>&nbsp;&nbsp;'
        '<a href="{}" style="color:#ba2121;">Delete</a>',
        update_url,
        delete_url,
    )


record_actions.short_description = "Actions"

@admin.register(LearnerSurvey)
class LearnerSurveyAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "learner",
        "course_id",
        "survey_id",
        "action",
        "created_at",
        "record_actions",
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
        "created_at",
        "updated_at",
        "survey_uuid",
    )

    def learner(self, obj):
        return f"{obj.user.username} ({obj.user.email})"
    learner.short_description = "Learner"
    learner.admin_order_field = "user__username"
    
    @admin.display(description="Actions")
    def record_actions(self, obj):
        return record_actions(obj)
