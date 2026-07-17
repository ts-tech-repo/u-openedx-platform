from django.urls import path, re_path
from . import views


urlpatterns = [
    path(
        "ping/",
        views.ping,
        name="custom-ping"
    ),
    
    re_path(r'^user/generate_jwt_token$', views.extras_generate_jwt_token, name = 'extras_generate_jwt_token')
]