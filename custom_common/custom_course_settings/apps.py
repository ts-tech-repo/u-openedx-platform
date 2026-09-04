from django.apps import AppConfig


class CustomCourseSettingsConfig(AppConfig):
    name = "custom_course_settings"

    def ready(self):
        from .course_fields import register_enable_certificate_field

        register_enable_certificate_field()