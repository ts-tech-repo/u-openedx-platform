"""
Pipeline step: make sure the identity returned by the IdP matches the email
the user typed on the custom login page.

On mismatch the SSO login is abandoned and the user is sent back to the login
page, where Phase 1 now asks for a password instead of SSO for that email
(see CUSTOM_PASSWORD_FALLBACK_SESSION_KEY).
"""
import logging
from urllib.parse import urlencode

from django.conf import settings

from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers

from .strategy import CUSTOM_OAUTH2_SESSION_KEY, CUSTOM_PASSWORD_FALLBACK_SESSION_KEY

log = logging.getLogger(__name__)


def _login_page_url(next_url=None):
    mfe_config = configuration_helpers.get_value('MFE_CONFIG', getattr(settings, 'MFE_CONFIG', {})) or {}
    authn_url = (mfe_config.get('AUTHN_MICROFRONTEND_URL') or '').rstrip('/')
    base_url = f"{authn_url}/login"
    return f"{base_url}?{urlencode({'next': next_url})}" if next_url else base_url


def enforce_expected_email(strategy, details, backend, *args, **kwargs):
    request = strategy.request
    marker = request.session.get(CUSTOM_OAUTH2_SESSION_KEY) if request else None

    # Not started from the custom login flow -> default behaviour untouched.
    if not marker or marker.get('backend_name') != backend.name:
        return None

    expected = (marker.get('expected_email') or '').strip().lower()
    actual = (details.get('email') or '').strip().lower()

    if expected and actual != expected:
        log.warning(
            "#AMANK enforce_expected_email: mismatch backend=%s expected=%s actual=%s "
            "-> falling back to password login",
            backend.name, expected, actual,
        )
        request.session.pop(CUSTOM_OAUTH2_SESSION_KEY, None)
        # Enable password login for this email on the next attempt
        request.session[CUSTOM_PASSWORD_FALLBACK_SESSION_KEY] = expected

        next_url = strategy.session_get('next')
        redirect_url = _login_page_url(next_url)

        log.info("#AMANK enforce_expected_email: redirecting to %s", redirect_url)
        # Returning a response halts the pipeline; do_complete() returns it as-is.
        return strategy.redirect(redirect_url)

    return None