
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('custom_lms', '0004_avlearners_avsummary'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='surveyresponse',
            unique_together=None,
        ),
        migrations.RemoveField(
            model_name='surveyresponse',
            name='user',
        ),
        migrations.RenameField(
            model_name='avlearners',
            old_name='kc_completed',
            new_name='checkpoints_completed',
        ),
        migrations.RenameField(
            model_name='avlearners',
            old_name='kc_total',
            new_name='checkpoints_total',
        ),
        migrations.RenameField(
            model_name='avsummary',
            old_name='av_kc_completed',
            new_name='av_checkpoints_completed',
        ),
        migrations.RenameField(
            model_name='avsummary',
            old_name='completed_kc_total',
            new_name='checkpoints_total',
        ),
        migrations.RenameField(
            model_name='avsummary',
            old_name='kc_total',
            new_name='completed_checkpoints_total',
        ),
        migrations.RenameIndex(
            model_name='avlearners',
            new_name='custom_lms__course__9c20fd_idx',
            old_name='custom_lms_avl_course_status_idx',
        ),
        migrations.RenameIndex(
            model_name='avlearners',
            new_name='custom_lms__course__b3294a_idx',
            old_name='custom_lms_avl_course_login_idx',
        ),
        migrations.RenameIndex(
            model_name='avsummary',
            new_name='custom_lms__course__13e602_idx',
            old_name='custom_lms_avs_course_idx',
        ),
        migrations.RenameIndex(
            model_name='learnersurvey',
            new_name='custom_lms__user_id_40b8f9_idx',
            old_name='custom_lms_learner_survey_idx',
        ),
        migrations.AlterField(
            model_name='learnersurvey',
            name='action',
            field=models.CharField(choices=[('name-validate', 'name-validated'), ('survey-submit', 'survey-submitted'), ('survey-skip', 'survey-skipped'), ('certificate', 'certificate-generated')], max_length=20),
        ),
        migrations.AlterField(
            model_name='learnersurvey',
            name='id',
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='learnersurvey',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='survey_responses', to=settings.AUTH_USER_MODEL),
        ),
        migrations.DeleteModel(
            name='SurveyResponse',
        ),
    ]
