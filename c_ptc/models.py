from django.conf import settings
from django.db import models
from django.utils import timezone


class UserPtcInfo(models.Model):
    """Stores PTC-related information for a user."""

    userid = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_ptc_infos",
        db_column="userid",
    )
    created_at = models.DateTimeField(default=timezone.now, auto_now_add=True)
    ptc_type = models.CharField(max_length=80)
    submitted_at = models.DateTimeField(null=True, blank=True)
    course_ids = models.JSONField(default=list, blank=True)
    metadata = models.CharField(max_length=4000, default="{}")
    modified_at = models.DateTimeField(default=timezone.now, auto_now=True)

    def __str__(self):
        return f"{self.userid} - {self.ptc_type}"

    class Meta:
        db_table = "user_ptc_info"
        verbose_name = "User PTC Info"
        verbose_name_plural = "User PTC Infos"
        constraints = [
            models.UniqueConstraint(
                fields=["userid", "ptc_type"],
                name="unique_userid_ptc_type",
            )
        ]
