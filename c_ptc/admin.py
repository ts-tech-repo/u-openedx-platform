from django.contrib import admin
from django.contrib.auth import get_user_model

from .models import UserPtcInfo

import logging

log = logging.getLogger(__name__)

User = get_user_model()


class UserPtcInfoInline(admin.StackedInline):
    model = UserPtcInfo
    extra = 0
    show_change_link = True

    fields = (
        "ptc_type",
        "submitted_at",
        "course_ids",
        "metadata",
        "created_at",
        "modified_at",
    )

    readonly_fields = (
        "created_at",
        "modified_at",
        "submitted_at",
    )

    verbose_name = "User PTC Info"
    verbose_name_plural = "User PTC Info"


# Attach the inline to the existing User admin
user_admin = admin.site._registry.get(User)
log.warning("User admin = %s", user_admin)

if user_admin:
    inlines = list(getattr(user_admin, "inlines", []))
    if UserPtcInfoInline not in inlines:
        inlines.append(UserPtcInfoInline)
        user_admin.inlines = inlines


@admin.register(UserPtcInfo)
class UserPtcInfoAdmin(admin.ModelAdmin):
    list_display = (
        "ptc_type",
        "submitted_at",
        "created_at",
    )

    search_fields = (
        "userid__username",
        "userid__email",
        "ptc_type",
    )

    readonly_fields = (
        "created_at",
        "modified_at",
    )

    fields = (
        "ptc_type",
        "submitted_at",
        "course_ids",
        "metadata",
        "created_at",
        "modified_at",
    )