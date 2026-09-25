from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

try:
    from opaque_keys.edx.django.models import CourseKeyField
    COURSE_ID_FIELD = CourseKeyField(max_length=255, db_index=True)
except ImportError:  # pragma: no cover
    COURSE_ID_FIELD = models.CharField(max_length=255, db_index=True)


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SurveyResponse",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("course_id", COURSE_ID_FIELD),
                ("survey_id", models.CharField(db_index=True, max_length=255)),
                ("action", models.CharField(choices=[("submit", "Submitted"), ("skip", "Skipped")], max_length=10)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="survey_responses",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "unique_together": {("user", "course_id", "survey_id")},
            },
        ),
        migrations.AddIndex(
            model_name="surveyresponse",
            index=models.Index(fields=["user", "course_id", "survey_id"], name="custom_lms_survey_user_idx"),
        ),
    ]