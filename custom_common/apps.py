from django.apps import AppConfig


class CustomCommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "custom_common"

    def ready(self):
        import custom_common.signals