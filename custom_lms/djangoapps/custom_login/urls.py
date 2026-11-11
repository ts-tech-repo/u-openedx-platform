"""
URLs for custom_login.

giving you:
    POST /cl/api/v1/user/login/   (two-phase: email-only, then email+password)
    GET/POST/PATCH/DELETE /custom_login/api/v1/configs/[...]
"""
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CustomLoginView, CustomOAuth2ProviderConfigViewSet

app_name = 'custom_login'

router = DefaultRouter()
router.register(r'configs', CustomOAuth2ProviderConfigViewSet, basename='custom-oauth2-provider-config')

urlpatterns = [
    path('api/v1/user/login/', CustomLoginView.as_view(), name='custom_login'),
    path('api/v1/', include(router.urls)),
]
