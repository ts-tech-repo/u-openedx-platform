from django.db import models
from django.conf import settings
from opaque_keys.edx.django.models import CourseKeyField


class AvLearners(models.Model):
    """
    One row per (learner, course). Powers the learner table.
    Denormalized on purpose — this is a read-optimized cache, not the
    source of truth (CourseEnrollment / grades / completion remain that).
    """
    STATUS_COMPLETED = 'completed'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_CHOICES = [
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_IN_PROGRESS, 'In Progress'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, db_index=True)
    course_id = CourseKeyField(max_length=255, db_index=True)
    name = models.CharField(max_length=255, blank=True, default='')
    enrolled_on = models.DateTimeField(null=True, blank=True)
    course_progress = models.PositiveIntegerField(default=0)        # percentage
    checkpoints_completed = models.PositiveIntegerField(default=0)
    checkpoints_total = models.PositiveIntegerField(default=11)
    last_login = models.DateTimeField(null=True, blank=True)
    program_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS)

    class Meta:
        app_label = 'custom_lms'
        verbose_name = 'AV Learner'
        verbose_name_plural = 'AV Learners'
        unique_together = [('user', 'course_id')]
        indexes = [
            models.Index(fields=['course_id', 'program_status']),
            models.Index(fields=['course_id', 'last_login']),
        ]

    def __str__(self):
        return f"{self.name} - {self.course_id}"


class AvSummary(models.Model):
    """
    One row per course. Powers the summary table.
    Denormalized on purpose — this is a read-optimized cache, not the
    source of truth (CourseEnrollment / grades / completion remain that).
    """
    course_id = CourseKeyField(max_length=255, db_index=True, unique=True)
    enrolled_count = models.PositiveIntegerField(default=0)
    in_progress_count = models.PositiveIntegerField(default=0)
    completed_count = models.PositiveIntegerField(default=0)
    completion_rate = models.PositiveIntegerField(default=0)  # percentage
    active_learners_count = models.PositiveIntegerField(default=0)
    av_checkpoints_completed = models.PositiveIntegerField(default=0)
    completed_checkpoints_total = models.PositiveIntegerField(default=0)
    checkpoints_total = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = 'custom_lms'
        verbose_name = 'AV Summary'
        verbose_name_plural = 'AV Summary'
        indexes = [
            models.Index(fields=['course_id']),
        ]
    def __str__(self):
        return f"{self.course_id} - Enrolled: {self.enrolled_count}, In Progress: {self.in_progress_count}, Completed: {self.completed_count}"

class AvSyncHistory(models.Model):
    """
    One row per sync run. Lets you see whether the nightly job actually
    ran, how long it took, and what broke if it did.
    """
    STATUS_RUNNING = 'running'
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_PARTIAL = 'partial'
    STATUS_CHOICES = [
        (STATUS_RUNNING, 'Running'),
        (STATUS_SUCCESS, 'Success'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_PARTIAL, 'Partial (some courses failed)'),
    ]
    TRIGGER_CRON = 'cron'
    TRIGGER_MANUAL = 'manual'
    TRIGGER_CHOICES = [(TRIGGER_CRON, 'Cron'), (TRIGGER_MANUAL, 'Manual')]

    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    trigger = models.CharField(max_length=16, choices=TRIGGER_CHOICES, default=TRIGGER_CRON)
    courses_processed = models.PositiveIntegerField(default=0)
    courses_failed = models.PositiveIntegerField(default=0)
    learners_processed = models.PositiveIntegerField(default=0)
    duration_seconds = models.FloatField(null=True, blank=True)
    error_message = models.TextField(blank=True, default='')

    class Meta:
        app_label = 'custom_lms'
        verbose_name = 'AV Sync History'
        verbose_name_plural = 'AV Sync History'
        ordering = ['-started_at']

    def __str__(self):
        return f"Sync {self.pk} [{self.status}] @ {self.started_at:%Y-%m-%d %H:%M}"

