"""
DRF serializers for email_domain_auth.
"""
from rest_framework import serializers

from .models import _normalize_email_domain, CustomOAuth2ProviderConfig

class CustomOAuth2ProviderConfigSerializer(serializers.ModelSerializer):
    """
    Admin CRUD serializer for CustomOAuth2ProviderConfig.

    `secret` is write-only so it is never echoed back in API responses.
    """

    class Meta:
        model = CustomOAuth2ProviderConfig
        fields = [
            'id', 'email_domain', 'site', 'backend_name',
            'key', 'secret', 'other_settings', 'enabled',
            'change_date', 'changed_by',
        ]
        read_only_fields = ['id', 'change_date', 'changed_by']
        extra_kwargs = {
            'secret': {'write_only': True},
        }

    def validate_email_domain(self, value):
        attrs = super().validate(attrs)
        domain = _normalize_email_domain(attrs.get('email_domain', getattr(self.instance, 'email_domain', '')))
        site = attrs.get('site', getattr(self.instance, 'site', None))
        qs = CustomOAuth2ProviderConfig.objects.filter(email_domain=domain, site=site)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
            {'email_domain': f"A configuration for '{domain}' already exists on this site."}
            )
        attrs['email_domain'] = domain
        return attrs
