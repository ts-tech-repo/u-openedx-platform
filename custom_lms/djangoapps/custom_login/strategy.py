"""
Strategy for custom_login.

Why this exists
---------------
Open edX's stock `ConfigurationModelStrategy.setting()` always reads the
OAuth client id / secret (and other settings) from `OAuth2ProviderConfig`
keyed by `backend.name`, and raises
"Can't fetch setting of a disabled backend/provider." when no enabled row
exists in Admin -> Third Party Auth -> Provider Configuration (OAuth).

This strategy subclasses the stock one (nothing in third_party_auth is
modified). When `CustomLoginView` has put a marker in the session (see
`CUSTOM_OAUTH2_SESSION_KEY`), the settings of the matching
`CustomOAuth2ProviderConfig` (KEY, SECRET, other_settings) are used, and
anything it does not define comes from Django settings - the admin
OAuth2ProviderConfig is NOT required.

Without the marker, behaviour is 100% stock (default flow untouched).

Activation
----------
`third_party_auth.settings.apply_settings()` force-sets SOCIAL_AUTH_STRATEGY
to the stock class, and `social_django.utils` reads it at import time, so
setting it in settings has no effect. `install()` (called from
CustomLoginConfig.ready()) points social_django at this class and patches
the provider Registry so the pipeline (/auth/complete/) also resolves the
provider from the custom config.
"""
import logging

from crum import get_current_request
from django.conf import settings
from django.contrib.sites.models import Site
from social_core.backends.oauth import OAuthAuth
from social_django.strategy import DjangoStrategy

from common.djangoapps.third_party_auth import provider as tpa_provider
from common.djangoapps.third_party_auth.models import OAuth2ProviderConfig
from common.djangoapps.third_party_auth.strategy import ConfigurationModelStrategy

log = logging.getLogger(__name__)

# Session key written by CustomLoginView right before redirecting into the
# python-social-auth pipeline. Value: {'email_domain', 'site_id', 'backend_name'}
CUSTOM_OAUTH2_SESSION_KEY = 'custom_login_oauth2_marker'

# Set by enforce_expected_email when the IdP identity != typed email.
# Value: the typed email (lowercased). Phase 1 then asks for a password
# instead of returning the SSO URL again.
CUSTOM_PASSWORD_FALLBACK_SESSION_KEY = 'custom_login_password_fallback_email'

# Handled by the stock strategy, never taken from the custom config.
_STOCK_ONLY_SETTINGS = ('LOGIN_ERROR_URL', 'MAX_SESSION_LENGTH', 'SECRET_KEY')

STRATEGY_PATH = 'custom_lms.djangoapps.custom_login.strategy.CustomConfigurationModelStrategy'

_INSTALLED = False

def _is_azuread_backend(backend):
    backend_name = (
        backend.name if hasattr(backend, 'name') else backend
    )
    return 'azuread-oauth2' in backend_name

def get_custom_config_for_backend(backend_name, request=None):
    """
    Return the enabled CustomOAuth2ProviderConfig referenced by the session
    marker for `backend_name`, or None (-> stock behaviour).
    """
    # Imported here to avoid circular imports at settings/startup time.
    from custom_lms.djangoapps.custom_login.models import CustomOAuth2ProviderConfig

    request = request or get_current_request()
    session = getattr(request, 'session', None) if request is not None else None
    marker = session.get(CUSTOM_OAUTH2_SESSION_KEY) if session is not None else None
    if not marker or marker.get('backend_name') != backend_name:
        return None

    try:
        site = Site.objects.get(pk=marker['site_id'])
    except (Site.DoesNotExist, KeyError):
        return None

    config = CustomOAuth2ProviderConfig.current(marker.get('email_domain'), site)
    if config and config.enabled and config.backend_name == backend_name:
        return config
    return None


def build_provider_config(custom_config):
    """
    Build an UNSAVED, in-memory OAuth2ProviderConfig from the custom config so
    the third_party_auth pipeline (/auth/complete/) works without an admin row.
    Never saved -> nothing appears in Admin -> Provider Configuration (OAuth).
    """
    values = {
        'enabled': True,
        'name': custom_config.backend_name,
        'slug': custom_config.backend_name,
        'backend_name': custom_config.backend_name,
        'key': custom_config.key,
        'secret': custom_config.secret,
        'other_settings': custom_config.other_settings or '',
        'site_id': custom_config.site_id,
        'visible': False,
    }
    allowed = {f.attname for f in OAuth2ProviderConfig._meta.concrete_fields}
    return OAuth2ProviderConfig(**{k: v for k, v in values.items() if k in allowed})


class CustomConfigurationModelStrategy(ConfigurationModelStrategy):
    """
    ConfigurationModelStrategy that uses CustomOAuth2ProviderConfig
    (per email domain) instead of OAuth2ProviderConfig (per backend) for OAuth2
    backends, when the session carries the marker set by CustomLoginView.
    """

    def _get_custom_config(self, backend):
        return get_custom_config_for_backend(backend.name, getattr(self, 'request', None))

    def setting(self, name, default=None, backend=None):
        if isinstance(backend, OAuthAuth):
            custom_config = self._get_custom_config(backend)
            if custom_config is not None:
                if name not in _STOCK_ONLY_SETTINGS:
                    try:
                        value = custom_config.get_setting(name)
                    except KeyError:
                        value = None
                    if value not in (None, ''):
                        log.info(
                            "#AMANK CustomConfigurationModelStrategy.setting: using custom config "
                            "for name=%s backend=%s email_domain=%s",
                            name, backend.name, custom_config.email_domain,
                        )
                        return value

                # FIX: do NOT fall back to super() with the backend - that hits
                # OAuth2ProviderConfig and raises for a missing admin row.
                if name == 'LOGIN_ERROR_URL':
                    # Stock auth_entry-aware error URL handling, provider check skipped.
                    return super().setting(name, default, None)
                # Global / backend-specific Django settings
                # (e.g. FIELDS_STORED_IN_SESSION, SOCIAL_AUTH_GOOGLE_OAUTH2_*).
                return DjangoStrategy.setting(self, name, default, backend)

        return super().setting(name, default, backend)


# ------------------------------------------------------------ registry patch
_original_get_from_pipeline = tpa_provider.Registry.get_from_pipeline.__func__
_original_get_enabled_by_backend_name = tpa_provider.Registry.get_enabled_by_backend_name.__func__


def _patched_get_from_pipeline(cls, running_pipeline):
    backend_name = (running_pipeline or {}).get('backend')
    custom_config = get_custom_config_for_backend(backend_name) if backend_name else None
    if custom_config is not None:
        return build_provider_config(custom_config)
    return _original_get_from_pipeline(cls, running_pipeline)


def _patched_get_enabled_by_backend_name(cls, backend_name):
    custom_config = get_custom_config_for_backend(backend_name)
    if custom_config is not None:
        yield build_provider_config(custom_config)
        return
    yield from _original_get_enabled_by_backend_name(cls, backend_name)


def install():
    """Activate the strategy + registry patch. Called from AppConfig.ready()."""
    global _INSTALLED  # pylint: disable=global-statement
    if _INSTALLED:
        return

    import social_django.utils as social_utils

    # load_strategy() reads this module global on every call.
    social_utils.STRATEGY = STRATEGY_PATH
    settings.SOCIAL_AUTH_STRATEGY = STRATEGY_PATH

    tpa_provider.Registry.get_from_pipeline = classmethod(_patched_get_from_pipeline)
    tpa_provider.Registry.get_enabled_by_backend_name = classmethod(_patched_get_enabled_by_backend_name)
    
    _install_azuread_tenant_patch()
    _install_azuread_uid_patch()

    _INSTALLED = True
    log.info("#AMANK custom_login: strategy=%s and Registry patch installed", STRATEGY_PATH)
    
# ------------------------------------------------- azuread tenant patch
def _custom_tenant_id(backend):
    """TENANT_ID from the matching CustomOAuth2ProviderConfig.other_settings, else None."""
    custom_config = get_custom_config_for_backend(backend.name)
    if custom_config is None:
        return None
    try:
        return custom_config.get_setting('TENANT_ID') or None
    except KeyError:
        return None


def _with_tenant(backend, url):
    if not _is_azuread_backend(backend):
        return url
    tenant_id = _custom_tenant_id(backend)
    if tenant_id and '/common/' in url:
        new_url = url.replace('/common/', f'/{tenant_id}/', 1)
        log.info("#AMANK azuread tenant patch: %s -> %s", url, new_url)
        return new_url
    return url


def _install_azuread_tenant_patch():
    from social_core.backends.azuread import AzureADOAuth2

    original_authorization_url = AzureADOAuth2.authorization_url
    original_access_token_url = AzureADOAuth2.access_token_url

    def authorization_url(self):
        return _with_tenant(self, original_authorization_url(self))

    def access_token_url(self):
        return _with_tenant(self, original_access_token_url(self))

    AzureADOAuth2.authorization_url = authorization_url
    AzureADOAuth2.access_token_url = access_token_url
    
def _install_azuread_uid_patch():
    from social_core.backends.azuread import AzureADOAuth2
    from social_core.exceptions import AuthTokenError

    def get_user_id(self, details, response):
        uid = (
            response.get('upn')
            or response.get('preferred_username')
            or response.get('email')
            or details.get('email')
        )

        if not isinstance(uid, str) or not uid.strip():
            log.error(
                "#AMANK Azure AD UID missing: available_claims=%s",
                sorted(response.keys()),
            )
            raise AuthTokenError(
                self,
                ValueError("Azure AD ID token has no usable user identity claim"),
            )

        uid = uid.strip().lower()

        log.info(
            "#AMANK Azure AD UID resolved: claim=%s",
            next(
                (
                    name for name in (
                        'upn', 'preferred_username', 'email'
                    )
                    if response.get(name)
                ),
                'details.email',
            ),
        )
        return uid

    AzureADOAuth2.get_user_id = get_user_id