from django.contrib import admin
from django.utils.html import format_html

from ..models.admin_view import AvLearners, AvSummary, AvSyncHistory


def _local_time_html(dt):
    """
    Return an HTML snippet that renders *dt* in the browser's local timezone
    using Django's default date/time style, e.g. "Sept. 8, 2026, 5:51 a.m."

    The <time> element carries the UTC ISO-8601 string; the inline script
    converts it on page load using the browser's Intl API.  Falls back to
    the raw UTC string when JS is disabled.
    """
    if dt is None:
        return "-"
    iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")  # always UTC
    return format_html(
        '<time data-utc="{iso}">{iso}</time>'
        "<script>"
        "(function(){{"
        "  var el=document.currentScript.previousSibling;"
        "  var d=new Date(el.dataset.utc);"
        # Build "Sept. 8, 2026" part
        "  var months=['Jan.','Feb.','March','April','May','June','July','Aug.','Sept.','Oct.','Nov.','Dec.'];"
        "  var datePart=months[d.getMonth()]+' '+d.getDate()+', '+d.getFullYear();"
        # Build "5:51 a.m." / "1:30 p.m." part  (no leading zero on hour)
        "  var h=d.getHours(),m=d.getMinutes();"
        "  var ampm=h<12?'a.m.':'p.m.';"
        "  var h12=h%12||12;"
        "  var timePart=h12+':'+(m<10?'0':'')+m+'\u00a0'+ampm;"
        "  el.textContent=datePart+', '+timePart;"
        "}})();"
        "</script>",
        iso=iso,
    )


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
        "enrolled_on_local",
        "last_login_local",
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
        "enrolled_on_local",
        "last_login_local",
    )
    ordering = ("-last_login",)
    date_hierarchy = "enrolled_on"

    @admin.display(description="Learner", ordering="user__username")
    def learner(self, obj):
        return f"{obj.user.username} ({obj.user.email})"

    @admin.display(description="Enrolled on", ordering="enrolled_on")
    def enrolled_on_local(self, obj):
        return _local_time_html(obj.enrolled_on)

    enrolled_on_local.allow_tags = True  # Django < 2.0 compat

    @admin.display(description="Last login", ordering="last_login")
    def last_login_local(self, obj):
        return _local_time_html(obj.last_login)

    last_login_local.allow_tags = True

    @admin.display(description="Progress %", ordering="course_progress")
    def course_progress_display(self, obj):
        pct = obj.course_progress or 0
        colour = "green" if pct >= 100 else ("orange" if pct >= 50 else "red")

        return format_html(
            '<span style="color:{}">{} %</span>',
            colour,
            f"{pct}",
        )

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
        "started_at_local",
        "finished_at_local",
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
        "started_at_local",
        "finished_at_local",
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

    @admin.display(description="Started at", ordering="started_at")
    def started_at_local(self, obj):
        return _local_time_html(obj.started_at)

    started_at_local.allow_tags = True

    @admin.display(description="Finished at", ordering="finished_at")
    def finished_at_local(self, obj):
        return _local_time_html(obj.finished_at)

    finished_at_local.allow_tags = True

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
