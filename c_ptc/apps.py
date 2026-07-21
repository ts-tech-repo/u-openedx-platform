from django.apps import AppConfig


class CustomPTCConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "c_ptc"
    
    def ready(self):
        import c_ptc.signals