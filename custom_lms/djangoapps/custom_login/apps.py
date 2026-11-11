import logging

from django.apps import AppConfig
from django.conf import settings

log = logging.getLogger(__name__)


class CustomLoginConfig(AppConfig):
    name = 'lms.djangoapps.custom_login'

    def ready(self):
        from .strategy import install
        install()

        step = 'lms.djangoapps.custom_login.pipeline.enforce_expected_email'
        anchor = 'social_core.pipeline.social_auth.social_details'
        pipeline = list(getattr(settings, 'SOCIAL_AUTH_PIPELINE', []))

        if step in pipeline:
            return
        if anchor not in pipeline:
            log.error(
                "#AMANK CustomLoginConfig.ready: anchor %s not in SOCIAL_AUTH_PIPELINE, "
                "enforce_expected_email NOT installed", anchor,
            )
            return

        pipeline.insert(pipeline.index(anchor) + 1, step)
        settings.SOCIAL_AUTH_PIPELINE = pipeline
        log.info("#AMANK CustomLoginConfig.ready: enforce_expected_email installed after %s", anchor)