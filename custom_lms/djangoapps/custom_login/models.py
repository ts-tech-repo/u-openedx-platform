"""
Models for email_domain_auth.
"""
import json
import logging

from config_models.models import ConfigurationModel
from crum import get_current_request
from django.conf import settings
from django.contrib.sites.models import Site
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from common.djangoapps.third_party_auth.models import clean_json

log = logging.getLogger(__name__)

# 24 hours. Entries are invalidated explicitly on save/delete, so a long TTL is safe.
CACHE_TIMEOUT = 24 * 60 * 60
PROVIDER_CACHE_TIMEOUT = getattr(settings, 'CUSTOM_OAUTH2_PROVIDER_CACHE_TIMEOUT', CACHE_TIMEOUT)


def _get_backend_name_choices():
    """
    Build (value, display) choices for `backend_name` from the configured
    `THIRD_PARTY_AUTH_BACKENDS` setting, so the admin/API shows a dropdown
    of valid python-social-auth backends instead of free text.
    """
    backends = getattr(settings, 'THIRD_PARTY_AUTH_BACKENDS', []) or []
    log.info(
        "#AMANK _get_backend_name_choices: THIRD_PARTY_AUTH_BACKENDS=%s",
        backends,
    )
    return [(backend, backend) for backend in backends]


def _normalize_email_domain(value):
    """Strip whitespace / leading '@' and lowercase, same as lookups do."""
    return (value or '').strip().lstrip('@').lower()


class CustomOAuth2ProviderConfig(ConfigurationModel):
    """
    Custom Provider Configuration (OAuth)

    A per-email-domain OAuth2 configuration for the new email-domain-based
    login flow. Field set is copied 1:1 from `OAuth2ProviderConfig`
    (backend_name, key, secret, other_settings) and adds `email_domain`.

    .. no_pii:
    """

    # Keyed by email_domain (+ site), same KEY_FIELDS pattern
    # OAuth2ProviderConfig uses for backend_name (+ site).
    KEY_FIELDS = ('email_domain', 'site')
    prefix = 'cust-oa2'

    # ConfigurationModel.current() caches lookups for this many seconds.
    cache_timeout = PROVIDER_CACHE_TIMEOUT

    email_domain = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name=_('Email domain'),
        help_text=_(
            "The email domain this OAuth2 configuration applies to, e.g. "
            "'example.com' (no '@', no leading dot). This is looked up "
            "during the email-only first step of login to decide whether "
            "to route the user into this third-party flow or ask for a "
            "password."
        ),
    )
    site = models.ForeignKey(
        Site,
        on_delete=models.CASCADE,
        verbose_name=_('Site'),
    )

    # --- Fields copied from OAuth2ProviderConfig ---------------------------
    backend_name = models.CharField(
        max_length=50, blank=False, db_index=True,
        help_text=(
            "Which python-social-auth OAuth2 provider backend to use. "
            "The list of backend choices is determined by the THIRD_PARTY_AUTH_BACKENDS setting."
            # To be precise, it's set by AUTHENTICATION_BACKENDS
            # which production.py sets from THIRD_PARTY_AUTH_BACKENDS
        )
    )
    key = models.TextField(blank=True, verbose_name="Client ID")
    secret = models.TextField(
        blank=True,
        verbose_name="Client Secret",
        help_text=(
            'For increased security, you can avoid storing this in your database by leaving '
            'this field blank and setting '
            'SOCIAL_AUTH_OAUTH_SECRETS = {"(backend name)": "secret", ...} '
            'in your instance\'s Django settings (or lms.yml)'
        )
    )
    other_settings = models.TextField(blank=True, help_text="Optional JSON object with advanced settings, if any.")
    # -------------------------------------------------------------------------

    class Meta:
        app_label = "third_party_auth"
        db_table = "third_party_auth_customoauth2providerconfig"
        verbose_name = "Custom Provider Configuration (OAuth)"
        verbose_name_plural = "Custom Provider Configuration (OAuth)"
        unique_together = (('email_domain', 'site'),)

    def __str__(self):
        return f"{self.email_domain} -> {self.backend_name} (enabled={self.enabled})"

    # ------------------------------------------------------------------ cache
    def _cache_key(self):
        return self.cache_key_name(self.email_domain, self.site)

    # -------------------------------------------------------------- uniqueness
    def _duplicate_exists(self):
        """True if ANOTHER row already uses this (email_domain, site)."""
        if not self.email_domain or not self.site_id:
            return False
        qs = type(self).objects.filter(email_domain=self.email_domain, site_id=self.site_id)
        if self.pk is not None:
            qs = qs.exclude(pk=self.pk)
        return qs.exists()

    def _validate_not_duplicate(self):
        if self._duplicate_exists():
            log.warning(
                "#AMANK CustomOAuth2ProviderConfig: duplicate rejected email_domain=%s site_id=%s pk=%s",
                self.email_domain, self.site_id, self.pk,
            )
            raise ValidationError({
                'email_domain': _(
                    "A configuration for email domain '%(domain)s' already exists on this site. "
                    "Edit the existing entry instead of creating a new one."
                ) % {'domain': self.email_domain},
            })

    def save(self, force_insert=False, force_update=False, using=None, update_fields=None):
        """
        Update the existing record in place instead of ConfigurationModel's
        default "always insert a new version" behaviour.

        * Existing row (pk set)  -> plain UPDATE.
        * New row, but a row for the same (email_domain, site) already exists
          -> REJECTED with ValidationError (no silent overwrite).
        * Otherwise -> INSERT.

        Caches for the old and new key are cleared afterwards.
        """
        # Normalise so the cache key always matches what
        # get_config_for_email() looks up (it lowercases the domain).
        self.email_domain = _normalize_email_domain(self.email_domain)

        # Block creating (or renaming into) an existing (email_domain, site).
        self._validate_not_duplicate()

        stale_keys = []
        if self.pk is not None:
            # Key (domain/site) may have been edited -> clear the OLD key too.
            previous = type(self).objects.select_related('site').filter(pk=self.pk).first()
            if previous:
                stale_keys.append(previous._cache_key())

        self.change_date = timezone.now()

        # Deliberately skip ConfigurationModel.save() (it forces pk=None).
        models.Model.save(
            self,
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

        stale_keys.append(self._cache_key())
        stale_keys.append(self.key_values_cache_key_name())
        cache.delete_many(stale_keys)

        log.info(
            "#AMANK CustomOAuth2ProviderConfig.save: pk=%s email_domain=%s "
            "cleared cache keys=%s", self.pk, self.email_domain, stale_keys,
        )

    # ----------------------------------------------------------------- config
    def clean(self):
        """ Standardize and validate fields """
        super().clean()
        self.email_domain = _normalize_email_domain(self.email_domain)
        self.other_settings = clean_json(self.other_settings, dict)

        # Shows a proper form error in Django admin instead of a 500.
        self._validate_not_duplicate()

        log.info(
            "#AMANK CustomOAuth2ProviderConfig.clean: email_domain=%s, "
            "backend_name=%s, site=%s, other_settings=%s",
            self.email_domain, self.backend_name,
            getattr(self, 'site_id', None), self.other_settings,
        )

    def get_setting(self, name):
        """ Get the value of a setting, or raise KeyError """
        if name == "KEY":
            return self.key
        if name == "SECRET":
            if self.secret:
                return self.secret
            # To allow instances to avoid storing secrets in the DB, the secret can also be set via Django:
            return getattr(settings, 'SOCIAL_AUTH_OAUTH_SECRETS', {}).get(self.backend_name, '')
        if self.other_settings:
            other_settings = json.loads(self.other_settings)
            assert isinstance(other_settings, dict), "other_settings should be a JSON object (dictionary)"
            return other_settings[name]

        log.warning(
            "#AMANK CustomOAuth2ProviderConfig.get_setting: no match for "
            "name=%s (email_domain=%s, backend_name=%s), raising KeyError",
            name, self.email_domain, self.backend_name,
        )
        raise KeyError

    @classmethod
    def current(cls, email_domain, site=None):
        """
        Same pattern as `OAuth2ProviderConfig.current(backend_name, site)`,
        keyed by `email_domain` instead of `backend_name`.
        """
        # If site not given, auto-detect
        if site is None:
            site = Site.objects.get_current(get_current_request())

        # ConfigurationModel.current() already caches this lookup
        # extra caching needed here.
        result = super(CustomOAuth2ProviderConfig, cls).current(email_domain, site)

        log.info(
            "#AMANK CustomOAuth2ProviderConfig.current: email_domain=%s, "
            "site=%s -> config=%s (enabled=%s)",
            email_domain, site, result, getattr(result, 'enabled', None),
        )
        return result

    @classmethod
    def get_config_for_email(cls, email, site=None):
        """
        Look up the enabled config for the domain of `email`.

        Returns the `CustomOAuth2ProviderConfig` instance if an enabled
        config exists for that domain (on the given/current site), else
        None.
        """
        if not email or '@' not in email:
            return None
        domain = email.rsplit('@', 1)[-1].strip().lower()

        # Resolve site once here and pass it through, so current() doesn't
        # redundantly call get_current_request()/get_current() again.
        if site is None:
            site = Site.objects.get_current(get_current_request())

        config = cls.current(domain, site)
        result = config if (config and config.enabled) else None

        log.info(
            "#AMANK CustomOAuth2ProviderConfig.get_config_for_email: "
            "email=%s -> domain=%s, site=%s, config=%s, returning=%s",
            email, domain, site, config, result,
        )
        return result


@receiver(post_delete, sender=CustomOAuth2ProviderConfig)
def _clear_custom_oauth2_cache_on_delete(sender, instance, **kwargs):
    """ConfigurationModel doesn't invalidate on delete (API DELETE / admin delete)."""
    try:
        keys = [instance._cache_key(), instance.key_values_cache_key_name()]
    except Site.DoesNotExist:  # site removed in the same cascade
        keys = [instance.key_values_cache_key_name()]
    cache.delete_many(keys)