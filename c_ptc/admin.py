from django.contrib import admin
from django.contrib.auth import get_user_model

from .models import UserPtcInfo

import logging

log = logging.getLogger(__name__)

User = get_user_model()


class UserPtcInfoInline(admin.TabularInline):
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
    )


# Append the inline to the existing User admin
user_admin = admin.site._registry.get(User)
log.warning("User admin = %s", user_admin)
if user_admin:
    if UserPtcInfoInline not in getattr(user_admin, "inlines", []):
        user_admin.inlines = list(getattr(user_admin, "inlines", []))
        user_admin.inlines.append(UserPtcInfoInline)


@admin.register(UserPtcInfo)
class UserPtcInfoAdmin(admin.ModelAdmin):
    list_display = (
        "userid",
        "ptc_type",
        "submitted_at",
        "created_at",
    )