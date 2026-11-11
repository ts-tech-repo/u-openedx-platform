"""
Django admin registration for email_domain_auth.
"""
from common.djangoapps.third_party_auth.models import _PSA_OAUTH2_BACKENDS

from django import forms
from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from .models import CustomOAuth2ProviderConfig

# Query param used by the "Duplicate" link to prefill the add form.
DUPLICATE_PARAM = 'duplicate_from'

# Fields copied from the source row when duplicating.
DUPLICATE_FIELDS = ('email_domain', 'site', 'backend_name', 'key', 'secret', 'other_settings', 'enabled')


class CustomOAuth2ProviderConfigForm(forms.ModelForm):
    """ Django Admin form class for CustomOAuth2ProviderConfig """
    backend_name = forms.ChoiceField(choices=((name, name) for name in _PSA_OAUTH2_BACKENDS))

    class Meta:
        model = CustomOAuth2ProviderConfig
        fields = '__all__'

    def clean_email_domain(self):
        return self.cleaned_data['email_domain'].strip().lstrip('@').lower()


class CustomOAuth2ProviderConfigAdmin(admin.ModelAdmin):
    """
    Admin UI for CustomOAuth2ProviderConfig.

    Edits update the same row (see CustomOAuth2ProviderConfig.save), so this is
    a normal ModelAdmin rather than a versioned/append-only ConfigurationModelAdmin.
    """
    form = CustomOAuth2ProviderConfigForm
    list_display = ('email_domain', 'site', 'backend_name', 'enabled', 'change_date', 'changed_by', 'duplicate_link')
    list_filter = ('enabled', 'site')
    search_fields = ('email_domain', 'backend_name')
    readonly_fields = ('change_date', 'changed_by')

    def get_queryset(self, request):
        # Hide any legacy history rows created before in-place updates.
        return self.model.objects.current_set().order_by('email_domain')

    def save_model(self, request, obj, form, change):
        obj.changed_by = request.user
        super().save_model(request, obj, form, change)

    # ------------------------------------------------------------- duplicate
    @admin.display(description='Duplicate')
    def duplicate_link(self, obj):
        """Opens the Add form prefilled with this row's values."""
        opts = self.model._meta
        url = reverse(f'admin:{opts.app_label}_{opts.model_name}_add')
        return format_html('<a class="button" href="{}?{}={}">Duplicate</a>', url, DUPLICATE_PARAM, obj.pk)

    def get_changeform_initial_data(self, request):
        """
        Prefill the Add form from ?duplicate_from=<pk>.
        Submission is still validated by the model's clean(), so saving with
        the same (email_domain, site) is rejected as a duplicate.
        """
        initial = super().get_changeform_initial_data(request)
        source_pk = initial.pop(DUPLICATE_PARAM, None)
        if not source_pk:
            return initial

        source = None
        if str(source_pk).isdigit():
            source = self.model.objects.filter(pk=source_pk).first()

        if source is None:
            messages.warning(request, f"Configuration #{source_pk} not found; opening an empty form.")
            return initial

        for field in DUPLICATE_FIELDS:
            initial[field] = source.site_id if field == 'site' else getattr(source, field)

        messages.info(
            request,
            f"Duplicating '{source.email_domain}'. Change the email domain or site before saving; "
            f"duplicates will be rejected."
        )
        return initial


admin.site.register(CustomOAuth2ProviderConfig, CustomOAuth2ProviderConfigAdmin)