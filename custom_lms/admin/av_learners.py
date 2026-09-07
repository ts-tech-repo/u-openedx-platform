from django.contrib import admin
from django.utils.html import format_html

from ..models.admin_view import AvLearners, AvSummary, AvSyncHistory


# --------------------------------------------------------------------------- #
#  AvLearners                                                                  #
# --------------------------------------------------------------------------- #

@admin.register(AvLearners)
class AvLearnersAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "learner",
        "course_id",
        "program_status",
        "course_progress_display",
        "checkpoints_completed",
        "checkpoints_total",
        "enrolled_on",
        "last_login",
    )
    list_filter = ("program_status",)
    search_fields = (
        "user__username",
        "user__email",
        "name",
        "course_id",
    )
    readonly_fields = (
        "user",
        "course_id",
        "enrolled_on",
        "last_login",
    )
    ordering = ("-last_login",)
    date_hierarchy = "enrolled_on"

    @admin.display(description="Learner", ordering="user__username")
    def learner(self, obj):
        return f"{obj.user.username} ({obj.user.email})"

    @admin.display(description="Progress %", ordering="course_progress")
    def course_progress_display(self, obj):
        pct = obj.course_progress
        colour = "green" if pct >= 100 else ("orange" if pct >= 50 else "red")
        return format_html('<span style="color:{}">{:.1f} %</span>', colour, pct)


# --------------------------------------------------------------------------- #
#  AvSummary                                                                   #
# --------------------------------------------------------------------------- #

@admin.register(AvSummary)
class AvSummaryAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "course_id",
        "enrolled_count",
        "in_progress_count",
        "completed_count",
        "completion_rate_display",
        "active_learners_count",
        "av_checkpoints_completed",
        "completed_checkpoints_total",
        "checkpoints_total",
    )
    search_fields = ("course_id",)
    readonly_fields = ("course_id",)
    ordering = ("course_id",)

    @admin.display(description="Completion rate %", ordering="completion_rate")
    def completion_rate_display(self, obj):
        return f"{obj.completion_rate:.1f} %"


# --------------------------------------------------------------------------- #
#  AvSyncHistory                                                               #
# --------------------------------------------------------------------------- #

@admin.register(AvSyncHistory)
class AvSyncHistoryAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "started_at",
        "finished_at",
        "status",
        "trigger",
        "courses_processed",
        "courses_failed",
        "learners_processed",
        "duration_seconds",
    )
    list_filter = ("status", "trigger")
    search_fields = ("error_message",)
    readonly_fields = (
        "started_at",
        "finished_at",
        "status",
        "trigger",
        "courses_processed",
        "courses_failed",
        "learners_processed",
        "duration_seconds",
        "error_message",
    )
    ordering = ("-started_at",)
    date_hierarchy = "started_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
