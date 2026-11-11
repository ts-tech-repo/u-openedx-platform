"""
email_domain_auth
Purpose
-------
The frontend calls one API, `LoginView` (`check_email/`), in two phases:

  Phase 1 - email only (no `password` in the POST body):
    Looks up the email's domain in `CustomOAuth2ProviderConfig` (fields
    copied from the existing `OAuth2ProviderConfig`, plus `email_domain`).
      * If an ENABLED config exists for that domain -> returns the
        backend_name/tpa_hint so the frontend can redirect into the
        standard, EXISTING python-social-auth third-party login flow
        (e.g. `/auth/login/<backend_name>/`). Nothing in
        `common/djangoapps/third_party_auth` is modified.
      * If no config exists -> returns a flag telling the frontend to show
        the password field.

  Phase 2 - email + password (same endpoint, called again):
    The request is delegated, UNCHANGED, to the existing
    `openedx.core.djangoapps.user_authn.views.login .login_user` function. That
    function is imported, not copied or modified -- this app performs
    exactly the same login (first-party auth, OTP, lockouts, cookies,
    third-party-link flow, etc.) as today's `/login_ajax` and
    `/api/user/v1/login_session` endpoints.

"""
