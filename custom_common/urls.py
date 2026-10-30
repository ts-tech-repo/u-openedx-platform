from django.urls import path, re_path
from . import views


urlpatterns = [
    path(
        "ping/",
        views.ping,
        name="custom-ping"
    ),
    
    re_path(r'^user/generate_jwt_token$', views.extras_generate_jwt_token, name = 'extras_generate_jwt_token'),
    re_path(r'^user/reset_password_link', views.extras_reset_password_link, name = "extras_reset_password_link"),
    
]