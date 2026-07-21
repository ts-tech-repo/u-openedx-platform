from django.urls import path
from . import views


urlpatterns = [
    path(
        "health/",
        views.health,
        name="c-ptc-health"
    ),
    path(
        "fetch/<str:ptc_type>",
        views.fetch_ptc,
        name="fetch-ptc"
    ),
    path(
        "submit/<str:ptc_type>",
        views.submit_ptc,
        name="submit-ptc"
    ),
]