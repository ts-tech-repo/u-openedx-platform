from django.apps import AppConfig


class CustomLmsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "custom_lms"

    def ready(self):
        import custom_lms.admin  # noqa: F401 — registers all admin classes