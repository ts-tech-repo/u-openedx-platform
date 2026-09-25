from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

try:
    from opaque_keys.edx.django.models import CourseKeyField
except ImportError:  # pragma: no cover
    CourseKeyField = None


def _course_key_field(**kwargs):
    if CourseKeyField is not None:
        return CourseKeyField(**kwargs)
    return models.CharField(**kwargs)  # pragma: no cover


class Migration(migrations.Migration):

    dependencies = [
        ("custom_lms", "0003_learnersurvey_survey_uuid"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ------------------------------------------------------------------ #
        #  AvLearners                                                         #
        # ------------------------------------------------------------------ #
        migrations.CreateModel(
            name="AvLearners",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("course_id", _course_key_field(max_length=255, db_index=True)),
                ("name", models.CharField(blank=True, default="", max_length=255)),
                ("enrolled_on", models.DateTimeField(blank=True, null=True)),
                ("course_progress", models.FloatField(default=0)),
                ("kc_completed", models.PositiveIntegerField(default=0)),
                ("kc_total", models.PositiveIntegerField(default=11)),
                ("last_login", models.DateTimeField(blank=True, null=True)),
                (
                    "program_status",
                    models.CharField(
                        choices=[
                            ("completed", "Completed"),
                            ("in_progress", "In Progress"),
                        ],
                        default="in_progress",
                        max_length=16,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        db_index=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "app_label": "custom_lms",
                "unique_together": {("user", "course_id")},
            },
        ),
        migrations.AddIndex(
            model_name="avlearners",
            index=models.Index(
                fields=["course_id", "program_status"],
                name="custom_lms_avl_course_status_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="avlearners",
            index=models.Index(
                fields=["course_id", "last_login"],
                name="custom_lms_avl_course_login_idx",
            ),
        ),
        # ------------------------------------------------------------------ #
        #  AvSummary                                                          #
        # ------------------------------------------------------------------ #
        migrations.CreateModel(
            name="AvSummary",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "course_id",
                    _course_key_field(max_length=255, db_index=True, unique=True),
                ),
                ("enrolled_count", models.PositiveIntegerField(default=0)),
                ("in_progress_count", models.PositiveIntegerField(default=0)),
                ("completed_count", models.PositiveIntegerField(default=0)),
                ("completion_rate", models.FloatField(default=0)),
                ("active_learners_count", models.PositiveIntegerField(default=0)),
                ("av_kc_completed", models.PositiveIntegerField(default=0)),
                ("completed_kc_total", models.PositiveIntegerField(default=0)),
                ("kc_total", models.PositiveIntegerField(default=0)),
            ],
            options={
                "app_label": "custom_lms",
            },
        ),
        migrations.AddIndex(
            model_name="avsummary",
            index=models.Index(
                fields=["course_id"],
                name="custom_lms_avs_course_idx",
            ),
        ),
        # ------------------------------------------------------------------ #
        #  AvSyncHistory                                                      #
        # ------------------------------------------------------------------ #
        migrations.CreateModel(
            name="AvSyncHistory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("started_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("running", "Running"),
                            ("success", "Success"),
                            ("failed", "Failed"),
                            ("partial", "Partial (some courses failed)"),
                        ],
                        default="running",
                        max_length=16,
                    ),
                ),
                (
                    "trigger",
                    models.CharField(
                        choices=[
                            ("cron", "Cron"),
                            ("manual", "Manual"),
                        ],
                        default="cron",
                        max_length=16,
                    ),
                ),
                ("courses_processed", models.PositiveIntegerField(default=0)),
                ("courses_failed", models.PositiveIntegerField(default=0)),
                ("learners_processed", models.PositiveIntegerField(default=0)),
                ("duration_seconds", models.FloatField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True, default="")),
            ],
            options={
                "app_label": "custom_lms",
                "ordering": ["-started_at"],
            },
        ),
    ]
