from django.apps import AppConfig


class CustomCommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "custom_common"

    def ready(self):
        import custom_common.signals
        from custom_common.custom_course_settings.course_fields import (
            register_enable_certificate_field,
        )

        register_enable_certificate_field()