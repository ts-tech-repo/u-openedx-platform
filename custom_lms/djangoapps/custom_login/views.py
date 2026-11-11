"""
Views for email_domain_auth.

1. CustomLoginView  (public, POST)  -- two phases, same endpoint:

   Phase 1 - frontend sends only `email` (no `password`):
       Looks up the email's domain in `CustomOAuth2ProviderConfig`.
         * Domain IS mapped to an enabled config
           -> HTTP 200 with `third_party_auth_required: true` and
              `sso_redirect_url`. The URL is built via
              the same `/auth/login/<backend>/` URL that
              Open edX uses (built from the custom config, no provider row needed). The frontend performs a full
              browser navigation to it (a raw 302 inside an XHR would be
              blocked by CORS at the IdP).
              The custom Client ID / Secret of the mapped config are used
              for the OAuth2 exchange (see strategy.py + session marker).
         * Domain is NOT mapped
           -> HTTP 200, `third_party_auth_required: false`,
              `password_required: true`. Frontend shows the password field.

   Phase 2 - frontend sends `email` + `password` (same endpoint, called a
   second time):
       The request is handed off, UNCHANGED, to the existing
       `openedx.core.djangoapps.user_authn.views.login.login_user` function.
       It runs exactly as it does for `/login_ajax` and
       `/api/user/v1/login_session` today and its response is returned as-is.

2. CustomOAuth2ProviderConfigViewSet  (admin only, full CRUD)
   Lets ops/admin manage the domain -> OAuth2 config mappings over API in
   addition to Django admin (/admin/third_party_auth/).

Caching:
   * Domain -> config lookups are cached by ConfigurationModel.current()
     (24h, cleared on save/delete; see models.py).
"""
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.http import QueryDict
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django_ratelimit.decorators import ratelimit
from rest_framework import permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from common.djangoapps.student.helpers import get_next_url_for_login_page
from common.djangoapps.third_party_auth import pipeline
# Imported, NOT modified. This is the exact same function that backs the
# existing `/login_ajax` and `/api/user/v1/login_session` endpoints.
from openedx.core.djangoapps.user_authn.views.login import login_user

from .models import CustomOAuth2ProviderConfig
from .serializers import CustomOAuth2ProviderConfigSerializer
# Session marker consumed by CustomConfigurationModelStrategy
from .strategy import CUSTOM_OAUTH2_SESSION_KEY, CUSTOM_PASSWORD_FALLBACK_SESSION_KEY

User = get_user_model()
log = logging.getLogger(__name__)


def _build_sso_login_url(backend_name, next_url=None):
    """
    Build `/auth/login/<backend_name>/?auth_entry=login&next=...` straight from
    the custom config's backend_name. Same URL pipeline.get_login_url() would
    produce, but without needing an OAuth2ProviderConfig row.
    """
    params = {getattr(pipeline, 'AUTH_ENTRY_KEY', 'auth_entry'): pipeline.AUTH_ENTRY_LOGIN}
    if next_url:
        params[getattr(pipeline, 'AUTH_REDIRECT_KEY', 'next')] = next_url
    return "{}?{}".format(
        reverse('social:begin', kwargs={'backend': backend_name}),
        urlencode(params),
    )


def _ensure_post_populated(request):
    """
    `login_user()` (old, unmodified code) reads its params via
    `request.POST`. That works out of the box when the frontend posts
    `application/x-www-form-urlencoded` or `multipart/form-data` (the same
    content type the existing `/login_ajax` already expects).

    If this endpoint is instead called with a JSON body, DRF's
    `request.POST` stays empty regardless of `request.data`, which would
    break the delegated call to `login_user()`. To keep `login_user()`
    completely untouched while still supporting a JSON body, we populate
    the underlying Django `HttpRequest.POST` from `request.data` whenever
    `POST` is empty, before handing the request off.
    """
    django_request = getattr(request, '_request', request)
    if not django_request.POST:
        query_dict = QueryDict('', mutable=True)
        query_dict.update(request.data)
        django_request.POST = query_dict

        log.info(
            "#AMANK _ensure_post_populated: repopulated django_request.POST "
            "from request.data, keys=%s",
            list(django_request.POST.keys()),
        )
    return django_request


@method_decorator(
    ratelimit(
        key='openedx.core.djangoapps.util.ratelimit.request_post_email_or_username',
        rate=settings.LOGISTRATION_PER_EMAIL_RATELIMIT_RATE,
        method='POST',
        block=False,
    ),
    name='post',
)
@method_decorator(
    ratelimit(
        key='openedx.core.djangoapps.util.ratelimit.real_ip',
        rate=settings.LOGISTRATION_RATELIMIT_RATE,
        method='POST',
        block=False,
    ),
    name='post',
)
class CustomLoginView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def _check_email_domain(self, request):
        if getattr(request, 'limited', False):
            log.warning(
                "#AMANK _check_email_domain: request rate-limited, remote_addr=%s",
                request.META.get('REMOTE_ADDR'),
            )
            return Response(
                {
                    'error_code': 'rate-limited',
                    'message': _('Too many requests. Try again shortly.'),
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        email = request.GET.get('email') or request.data.get('email', '').strip()

        if not email:
            return Response(
                {
                    'third_party_auth_required': False,
                    'password_required': False,
                    'error': True,
                    'message': _('Please enter your email address.'),
                },
                status=status.HTTP_200_OK,
            )

        email = email.lower()
        site = getattr(request, 'site', None) or Site.objects.get_current(request)

        # If SSO identity did not match the entered email, request a password.
        fallback_email = request.session.get(CUSTOM_PASSWORD_FALLBACK_SESSION_KEY)
        if fallback_email and fallback_email == email:
            request.session.pop(CUSTOM_OAUTH2_SESSION_KEY, None)
            log.info(
                "#AMANK _check_email_domain: password fallback active for email=%s",
                email,
            )
            return Response(
                {
                    'third_party_auth_required': False,
                    'password_required': True,
                    'user_exists': True,
                    'message': _(
                        'The signed-in account did not match this email. '
                        'Please enter your password to continue.'
                    ),
                },
                status=status.HTTP_200_OK,
            )

        # Cached (24h) domain -> config lookup.
        config = CustomOAuth2ProviderConfig.get_config_for_email(email, site=site)

        log.info(
            "#AMANK _check_email_domain: email=%s site=%s config=%s backend_name=%s",
            email, site, config, getattr(config, 'backend_name', None),
        )

        if config:
            # Tell CustomConfigurationModelStrategy to use THIS config's
            # Client ID / Secret / other_settings for the whole OAuth2 round
            # trip (/auth/login/<backend>/ -> IdP -> /auth/complete/<backend>/).
            request.session[CUSTOM_OAUTH2_SESSION_KEY] = {
                'email_domain': config.email_domain,
                'site_id': config.site_id,
                'backend_name': config.backend_name,
                'expected_email': email,
            }
            next_url = get_next_url_for_login_page(request)
            login_url = _build_sso_login_url(config.backend_name, next_url)

            log.info(
                "#AMANK _check_email_domain: returning third-party "
                "login_url=%s for email=%s",
                login_url, email,
            )

            return Response(
                {
                    'third_party_auth_required': True,
                    'password_required': False,
                    'user_exists': True,
                    'sso_redirect_url': login_url,
                },
                status=status.HTTP_200_OK,
            )

        # Unmapped domain -> make sure a stale marker never leaks into a
        # later, unrelated third-party login from the same session.
        request.session.pop(CUSTOM_OAUTH2_SESSION_KEY, None)
        return Response(
            {
                'third_party_auth_required': False,
                'password_required': True,
                'user_exists': True,
                'message': _('Please enter your password to continue.'),
            },
            status=status.HTTP_200_OK,
        )

    def _verify_sso_result(self, request):
        """
        Called by the frontend when the user lands back on the login page after
        the IdP round trip (POST {email, sso_verify: true}). NEVER returns an SSO
        URL, so it cannot loop the user back to the IdP.

          * Logged in as this email (SSO identity matched)
              -> {verified: true, redirect_url: <next>}
          * Identity did NOT match (pipeline.enforce_expected_email left the
            fallback marker for this email)
              -> {verified: false, password_required: true, message}
          * Anything else (SSO never finished / expired)
              -> {verified: false, password_required: false}
        """
        email = (request.data.get('email') or '').strip().lower()
        # `authentication_classes = []` makes request.user anonymous; the Django
        # session user set by AuthenticationMiddleware lives on the raw request.
        django_request = getattr(request, '_request', request)
        user = getattr(django_request, 'user', None)

        if (
            email
            and user is not None
            and user.is_authenticated
            and (user.email or '').strip().lower() == email
        ):
            request.session.pop(CUSTOM_OAUTH2_SESSION_KEY, None)
            request.session.pop(CUSTOM_PASSWORD_FALLBACK_SESSION_KEY, None)
            log.info("#AMANK _verify_sso_result: verified email=%s", email)
            return Response(
                {
                    'verified': True,
                    'redirect_url': get_next_url_for_login_page(request),
                },
                status=status.HTTP_200_OK,
            )

        fallback_email = request.session.get(CUSTOM_PASSWORD_FALLBACK_SESSION_KEY)
        if email and fallback_email == email:
            log.info("#AMANK _verify_sso_result: mismatch, password fallback email=%s", email)
            return Response(
                {
                    'verified': False,
                    'third_party_auth_required': False,
                    'password_required': True,
                    'user_exists': True,
                    'message': _('SSO is not available for this account. Please use your password.'),
                },
                status=status.HTTP_200_OK,
            )

        log.info("#AMANK _verify_sso_result: nothing to verify for email=%s", email)
        return Response(
            {'verified': False, 'password_required': False},
            status=status.HTTP_200_OK,
        )

    def get(self, request, *args, **kwargs):
        return self._check_email_domain(request)

    def post(self, request, *args, **kwargs):
        # Returning from the IdP: frontend asks "did the SSO identity match?"
        if request.data.get('sso_verify'):
            return self._verify_sso_result(request)

        password = request.data.get('password')

        # Phase 2: password supplied -> existing login_user()
        if password:
            api_version = (
                kwargs.get('api_version')
                or request.data.get('api_version', 'v1')
            )
            django_request = _ensure_post_populated(request)

            response = login_user(
                django_request,
                api_version=api_version,
            )

            log.info(
                "#AMANK CustomLoginView.post: login_user() returned status_code=%s",
                getattr(response, 'status_code', None),
            )

            if getattr(response, 'status_code', None) == 200:
                request.session.pop(CUSTOM_PASSWORD_FALLBACK_SESSION_KEY, None)

            return response

        # Phase 1: email only
        return self._check_email_domain(request)


class CustomOAuth2ProviderConfigViewSet(viewsets.ModelViewSet):
    """
    Admin-only CRUD API for managing email-domain -> OAuth2 config mappings.

    GET    /email_domain_auth/api/v1/configs/
    POST   /email_domain_auth/api/v1/configs/
    GET    /email_domain_auth/api/v1/configs/{id}/
    PATCH  /email_domain_auth/api/v1/configs/{id}/
    DELETE /email_domain_auth/api/v1/configs/{id}/

    Updates modify the same row in place and clear the related caches
    (see CustomOAuth2ProviderConfig.save and the post_delete receiver).
    """
    permission_classes = (permissions.IsAuthenticated, permissions.IsAdminUser)
    serializer_class = CustomOAuth2ProviderConfigSerializer

    def get_queryset(self):
        return CustomOAuth2ProviderConfig.objects.current_set().order_by('email_domain')

    def perform_create(self, serializer):
        serializer.save(changed_by=self.request.user)
        log.info(
            "#AMANK CustomOAuth2ProviderConfigViewSet.perform_create: "
            "user=%s created config instance=%s",
            self.request.user, serializer.instance,
        )

    def perform_update(self, serializer):
        serializer.save(changed_by=self.request.user)
        log.info(
            "#AMANK CustomOAuth2ProviderConfigViewSet.perform_update: "
            "user=%s updated config instance=%s",
            self.request.user, serializer.instance,
        )