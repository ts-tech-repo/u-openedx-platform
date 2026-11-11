# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.conf import settings
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True
    

    operations = [
        migrations.CreateModel(
            name='CustomOAuth2ProviderConfig',
            fields=[
                (
                    'id',
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'change_date',
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name='Change date',
                    ),
                ),
                (
                    'changed_by',
                    models.ForeignKey(
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        to=settings.AUTH_USER_MODEL,
                        verbose_name='Changed by',
                    ),
                ),
                (
                    'enabled',
                    models.BooleanField(
                        default=False,
                        help_text='If disabled, the configuration will not be used.',
                    ),
                ),
                (
                    'email_domain',
                    models.CharField(
                        db_index=True,
                        max_length=255,
                        verbose_name='Email domain',
                        help_text=(
                            "The email domain this OAuth2 configuration applies to, "
                            "e.g. 'example.com' (no '@', no leading dot). "
                            "This is looked up during the email-only first step "
                            "of login to decide whether to route the user into "
                            "this third-party flow or ask for a password."
                        ),
                    ),
                ),
                (
                    'backend_name',
                    models.CharField(
                        db_index=True,
                        max_length=50,
                        help_text=(
                            "Which python-social-auth OAuth2 provider backend to use. "
                            "The list of backend choices is determined by the "
                            "THIRD_PARTY_AUTH_BACKENDS setting."
                        ),
                    ),
                ),
                (
                    'key',
                    models.TextField(
                        blank=True,
                        verbose_name='Client ID',
                    ),
                ),
                (
                    'secret',
                    models.TextField(
                        blank=True,
                        verbose_name='Client Secret',
                        help_text=(
                            'For increased security, you can avoid storing this '
                            'in your database by leaving this field blank and '
                            'setting SOCIAL_AUTH_OAUTH_SECRETS = '
                            '{"(backend name)": "secret", ...} '
                            "in your instance's Django settings (or lms.yml)"
                        ),
                    ),
                ),
                (
                    'other_settings',
                    models.TextField(
                        blank=True,
                        help_text='Optional JSON object with advanced settings, if any.',
                    ),
                ),
                (
                    'site',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to='sites.Site',
                        verbose_name='Site',
                    ),
                ),
            ],
            options={
                'db_table': 'third_party_auth_customoauth2providerconfig',
                'verbose_name': 'Custom Provider Configuration (OAuth)',
                'verbose_name_plural': 'Custom Provider Configuration (OAuth)',
                'unique_together': (('email_domain', 'site'),),
            },
            
        ),
    ]