from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("custom_lms", "0005_rename_kc_to_checkpoints"),
    ]

    operations = [
        migrations.AlterField(
            model_name="avlearners",
            name="course_progress",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="avsummary",
            name="completion_rate",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterModelOptions(
            name="avlearners",
            options={
                "verbose_name": "AV Learner",
                "verbose_name_plural": "AV Learners",
            },
        ),
        migrations.AlterModelOptions(
            name="avsummary",
            options={
                "verbose_name": "AV Summary",
                "verbose_name_plural": "AV Summary",
            },
        ),
        migrations.AlterModelOptions(
            name="avsynchistory",
            options={
                "ordering": ["-started_at"],
                "verbose_name": "AV Sync History",
                "verbose_name_plural": "AV Sync History",
            },
        ),
    ]
