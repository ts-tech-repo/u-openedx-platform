import uuid

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("custom_lms", "0002_learnersurvey"),
    ]

    operations = [
        migrations.AddField(
            model_name="learnersurvey",
            name="survey_uuid",
            field=models.UUIDField(
                default=uuid.uuid4,
                editable=False,
                unique=True,
                db_index=True,
            ),
        ),
    ]
