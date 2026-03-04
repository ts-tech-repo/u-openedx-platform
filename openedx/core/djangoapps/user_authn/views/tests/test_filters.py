"""
Test that various filters are fired for the vies in the user_authn app.
"""
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from openedx_filters import PipelineStep
from openedx_filters.learning.filters import (
    LogistrationMFERedirectRequested,
    StudentLoginRequested,
    StudentRegistrationRequested,
)
from rest_framework import status

from common.djangoapps.student.tests.factories import UserFactory, UserProfileFactory
from common.djangoapps.third_party_auth.tests.testutil import ThirdPartyAuthTestMixin, simulate_running_pipeline
from openedx.core.djangoapps.user_api.tests.test_views import UserAPITestCase
from openedx.core.djangolib.testing.utils import skip_unless_lms

User = get_user_model()


class TestRegisterPipelineStep(PipelineStep):
    """
    Utility function used when getting steps for pipeline.
    """

    def run_filter(self, form_data):  # pylint: disable=arguments-differ
        """Pipeline steps that changes the user's username."""
        username = f"{form_data.get('username')}-OpenEdx"
        form_data["username"] = username
        return {
            "form_data": form_data,
        }


class TestAnotherRegisterPipelineStep(PipelineStep):
    """
    Utility function used when getting steps for pipeline.
    """

    def run_filter(self, form_data):  # pylint: disable=arguments-differ
        """Pipeline steps that changes the user's username."""
        username = f"{form_data.get('username')}-Test"
        form_data["username"] = username
        return {
            "form_data": form_data,
        }


class TestStopRegisterPipelineStep(PipelineStep):
    """
    Utility function used when getting steps for pipeline.
    """

    def run_filter(self, form_data):  # pylint: disable=arguments-differ
        """Pipeline steps that stops the user's registration process."""
        raise StudentRegistrationRequested.PreventRegistration("You can't register on this site.", status_code=403)


class TestLoginPipelineStep(PipelineStep):
    """
    Utility function used when getting steps for pipeline.
    """

    def run_filter(self, user):  # pylint: disable=arguments-differ
        """Pipeline steps that adds a field to the user's profile."""
        user.profile.set_meta({"logged_in": True})
        user.profile.save()
        return {
            "user": user
        }


class TestAnotherLoginPipelineStep(PipelineStep):
    """
    Utility function used when getting steps for pipeline.
    """

    def run_filter(self, user):  # pylint: disable=arguments-differ
        """Pipeline steps that adds a field to the user's profile."""
        new_meta = user.profile.get_meta()
        new_meta.update({"another_logged_in": True})
        user.profile.set_meta(new_meta)
        user.profile.save()
        return {
            "user": user
        }


class TestStopLoginPipelineStep(PipelineStep):
    """
    Utility function used when getting steps for pipeline.
    """

    def run_filter(self, user):  # pylint: disable=arguments-differ
        """Pipeline steps that stops the user's login."""
        raise StudentLoginRequested.PreventLogin("You can't login on this site.")


@skip_unless_lms
class RegistrationFiltersTest(UserAPITestCase):
    """
    Tests for the Open edX Filters associated with the user registration process.

    This class guarantees that the following filters are triggered during the user's registration:

    - StudentRegistrationRequested
    """

    def setUp(self):  # pylint: disable=arguments-differ
        super().setUp()
        self.url = reverse("user_api_registration")
        self.user_info = {
            "email": "user@example.com",
            "name": "Test User",
            "username": "test",
            "password": "password",
            "honor_code": "true",
        }

    @override_settings(
        OPEN_EDX_FILTERS_CONFIG={
            "org.openedx.learning.student.registration.requested.v1": {
                "pipeline": [
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestRegisterPipelineStep",
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestAnotherRegisterPipelineStep",
                ],
                "fail_silently": False,
            },
        },
    )
    def test_register_filter_executed(self):
        """
        Test whether the student register filter is triggered before the user's
        registration process.

        Expected result:
            - StudentRegistrationRequested is triggered and executes TestRegisterPipelineStep.
            - The user's username is updated.
        """
        self.client.post(self.url, self.user_info)

        user = User.objects.filter(username=f"{self.user_info.get('username')}-OpenEdx-Test")
        self.assertTrue(user)  # noqa: PT009

    @override_settings(
        OPEN_EDX_FILTERS_CONFIG={
            "org.openedx.learning.student.registration.requested.v1": {
                "pipeline": [
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestRegisterPipelineStep",
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestStopRegisterPipelineStep",
                ],
                "fail_silently": False,
            },
        },
    )
    def test_register_filter_prevent_registration(self):
        """
        Test prevent the user's registration through a pipeline step.

        Expected result:
            - StudentRegistrationRequested is triggered and executes TestStopRegisterPipelineStep.
            - The user's registration stops.
        """
        response = self.client.post(self.url, self.user_info)

        self.assertEqual(status.HTTP_403_FORBIDDEN, response.status_code)  # noqa: PT009

    @override_settings(OPEN_EDX_FILTERS_CONFIG={})
    def test_register_without_filter_configuration(self):
        """
        Test usual registration process, without filter's intervention.

        Expected result:
            - StudentRegistrationRequested does not have any effect on the registration process.
            - The registration process ends successfully.
        """
        self.client.post(self.url, self.user_info)

        user = User.objects.filter(username=f"{self.user_info.get('username')}")
        self.assertTrue(user)  # noqa: PT009


@skip_unless_lms
class LoginFiltersTest(UserAPITestCase):
    """
    Tests for the Open edX Filters associated with the user login process.

    This class guarantees that the following filters are triggered during the user's login:

    - StudentLoginRequested
    """

    def setUp(self):  # pylint: disable=arguments-differ
        super().setUp()
        self.user = UserFactory.create(
            username="test",
            email="test@example.com",
            password="password",
        )
        self.user_profile = UserProfileFactory.create(user=self.user, name="Test Example")
        self.url = reverse('login_api')

    @override_settings(
        OPEN_EDX_FILTERS_CONFIG={
            "org.openedx.learning.student.login.requested.v1": {
                "pipeline": [
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestLoginPipelineStep",
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestAnotherLoginPipelineStep",
                ],
                "fail_silently": False,
            },
        },
    )
    def test_login_filter_executed(self):
        """
        Test whether the student login filter is triggered before the user's
        login process.

        Expected result:
            - StudentLoginRequested is triggered and executes TestLoginPipelineStep.
            - The user's profile is updated.
        """
        data = {
            "email": "test@example.com",
            "password": "password",
        }

        self.client.post(self.url, data)

        user = User.objects.get(username=self.user.username)
        self.assertDictEqual({"logged_in": True, "another_logged_in": True}, user.profile.get_meta())  # noqa: PT009

    @override_settings(
        OPEN_EDX_FILTERS_CONFIG={
            "org.openedx.learning.student.login.requested.v1": {
                "pipeline": [
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestLoginPipelineStep",
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestStopLoginPipelineStep",
                ],
                "fail_silently": False,
            },
        },
    )
    def test_login_filter_prevent_login(self):
        """
        Test prevent the user's login through a pipeline step.

        Expected result:
            - StudentLoginRequested is triggered and executes TestStopLoginPipelineStep.
            - Test prevent the user's login through a pipeline step.
        """
        data = {
            "email": "test@example.com",
            "password": "password",
        }

        response = self.client.post(self.url, data)

        self.assertEqual(status.HTTP_400_BAD_REQUEST, response.status_code)  # noqa: PT009

    @override_settings(OPEN_EDX_FILTERS_CONFIG={})
    def test_login_without_filter_configuration(self):
        """
        Test usual login process, without filter's intervention.

        Expected result:
            - StudentLoginRequested does not have any effect on the login process.
            - The login process ends successfully.
        """
        data = {
            "email": "test@example.com",
            "password": "password",
        }

        response = self.client.post(self.url, data)

        self.assertEqual(status.HTTP_200_OK, response.status_code)  # noqa: PT009


class TestFormDescriptionPipelineStep(PipelineStep):
    """
    Utility class used when getting steps for pipeline.
    """

    def run_filter(self, form_desc, running_pipeline, current_provider):  # pylint: disable=arguments-differ
        """Pipeline step that overrides the default value of the email field."""
        form_desc.override_field_properties("email", default="filtered@example.com")
        return {
            "form_desc": form_desc,
            "running_pipeline": running_pipeline,
            "current_provider": current_provider,
        }


class TestLogistrationContextPipelineStep(PipelineStep):
    """
    Utility class used when getting steps for pipeline.
    """

    def run_filter(self, context):  # pylint: disable=arguments-differ
        """Pipeline step that modifies the logistration page context."""
        context["data"]["platform_name"] = "Filtered Platform Name"
        return {
            "context": context,
        }


class TestLogistrationResponsePipelineStep(PipelineStep):
    """
    Utility class used when getting steps for pipeline.
    """

    def run_filter(self, response, context):  # pylint: disable=arguments-differ
        """Pipeline step that sets a cookie on the logistration response."""
        response.set_cookie("logistration-filter", "applied")
        return {
            "response": response,
            "context": context,
        }


class TestPreventMFERedirectPipelineStep(PipelineStep):
    """
    Utility class used when getting steps for pipeline.
    """

    def run_filter(self, request):  # pylint: disable=arguments-differ
        """Pipeline step that keeps the user on the legacy logistration page."""
        raise LogistrationMFERedirectRequested.PreventRedirect("Legacy page required.")


class TestPostLoginRedirectPipelineStep(PipelineStep):
    """
    Utility class used when getting steps for pipeline.
    """

    def run_filter(self, redirect_url, user, next_url):  # pylint: disable=arguments-differ
        """Pipeline step that overrides the post-login redirect URL."""
        return {
            "redirect_url": "/custom/post/login",
            "user": user,
            "next_url": next_url,
        }


@skip_unless_lms
class LoginFormTPAOverridesFiltersTest(ThirdPartyAuthTestMixin, UserAPITestCase):
    """
    Tests for the Open edX Filters associated with the login form description.

    This class guarantees that the following filters are triggered while the login form
    description is built during a running third-party-auth pipeline:

    - LoginFormTPAOverridesRequested
    """

    def setUp(self):  # pylint: disable=arguments-differ
        super().setUp()
        self.url = reverse("user_api_login_session", kwargs={"api_version": "v1"})
        self.configure_google_provider(enabled=True)

    @override_settings(
        OPEN_EDX_FILTERS_CONFIG={
            "org.openedx.learning.login.form.tpa_overrides.requested.v1": {
                "pipeline": [
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestFormDescriptionPipelineStep",
                ],
                "fail_silently": False,
            },
        },
    )
    def test_login_form_tpa_overrides_filter_executed(self):
        """
        Test whether the login form TPA overrides filter is triggered while the form is
        built during a running third-party-auth pipeline.

        Expected result:
            - LoginFormTPAOverridesRequested is triggered and executes TestFormDescriptionPipelineStep.
            - The email field default is overridden in the serialized form description.
        """
        with simulate_running_pipeline(
            "openedx.core.djangoapps.user_authn.views.login_form.third_party_auth.pipeline",
            "google-oauth2",
        ):
            response = self.client.get(self.url)

        self.assertContains(response, "filtered@example.com")

    @override_settings(
        OPEN_EDX_FILTERS_CONFIG={
            "org.openedx.learning.login.form.tpa_overrides.requested.v1": {
                "pipeline": [
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestFormDescriptionPipelineStep",
                ],
                "fail_silently": False,
            },
        },
    )
    def test_login_form_tpa_overrides_without_running_pipeline(self):
        """
        Test that the login form TPA overrides filter is not triggered without a running
        third-party-auth pipeline, even when a pipeline step is configured.

        Expected result:
            - LoginFormTPAOverridesRequested does not have any effect on the form description.
        """
        response = self.client.get(self.url)

        self.assertEqual(status.HTTP_200_OK, response.status_code)  # noqa: PT009
        self.assertNotContains(response, "filtered@example.com")

    @override_settings(OPEN_EDX_FILTERS_CONFIG={})
    def test_login_form_tpa_overrides_without_filter_configuration(self):
        """
        Test usual login form description, without filter's intervention.

        Expected result:
            - LoginFormTPAOverridesRequested does not have any effect on the form description.
        """
        with simulate_running_pipeline(
            "openedx.core.djangoapps.user_authn.views.login_form.third_party_auth.pipeline",
            "google-oauth2",
        ):
            response = self.client.get(self.url)

        self.assertEqual(status.HTTP_200_OK, response.status_code)  # noqa: PT009
        self.assertNotContains(response, "filtered@example.com")


@skip_unless_lms
class RegistrationFormTPAOverridesFiltersTest(ThirdPartyAuthTestMixin, UserAPITestCase):
    """
    Tests for the Open edX Filters associated with the registration form description.

    This class guarantees that the following filters are triggered while the registration
    form description is built during a running third-party-auth pipeline:

    - RegistrationFormTPAOverridesRequested
    """

    def setUp(self):  # pylint: disable=arguments-differ
        super().setUp()
        self.url = reverse("user_api_registration")
        self.configure_google_provider(enabled=True)

    @override_settings(
        OPEN_EDX_FILTERS_CONFIG={
            "org.openedx.learning.registration.form.tpa_overrides.requested.v1": {
                "pipeline": [
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestFormDescriptionPipelineStep",
                ],
                "fail_silently": False,
            },
        },
    )
    def test_registration_form_tpa_overrides_filter_executed(self):
        """
        Test whether the registration form TPA overrides filter is triggered while the
        form is built during a running third-party-auth pipeline.

        Expected result:
            - RegistrationFormTPAOverridesRequested is triggered and executes TestFormDescriptionPipelineStep.
            - The email field default is overridden in the serialized form description.
        """
        with simulate_running_pipeline(
            "openedx.core.djangoapps.user_authn.views.registration_form.third_party_auth.pipeline",
            "google-oauth2",
            email="pipeline@example.com",
        ):
            response = self.client.get(self.url)

        self.assertContains(response, "filtered@example.com")

    @override_settings(
        OPEN_EDX_FILTERS_CONFIG={
            "org.openedx.learning.registration.form.tpa_overrides.requested.v1": {
                "pipeline": [
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestFormDescriptionPipelineStep",
                ],
                "fail_silently": False,
            },
        },
    )
    def test_registration_form_tpa_overrides_without_running_pipeline(self):
        """
        Test that the registration form TPA overrides filter is not triggered without a
        running third-party-auth pipeline, even when a pipeline step is configured.

        Expected result:
            - RegistrationFormTPAOverridesRequested does not have any effect on the form description.
        """
        response = self.client.get(self.url)

        self.assertEqual(status.HTTP_200_OK, response.status_code)  # noqa: PT009
        self.assertNotContains(response, "filtered@example.com")

    @override_settings(OPEN_EDX_FILTERS_CONFIG={})
    def test_registration_form_tpa_overrides_without_filter_configuration(self):
        """
        Test usual registration form description, without filter's intervention.

        Expected result:
            - RegistrationFormTPAOverridesRequested does not have any effect on the form description.
        """
        with simulate_running_pipeline(
            "openedx.core.djangoapps.user_authn.views.registration_form.third_party_auth.pipeline",
            "google-oauth2",
            email="pipeline@example.com",
        ):
            response = self.client.get(self.url)

        self.assertEqual(status.HTTP_200_OK, response.status_code)  # noqa: PT009
        self.assertNotContains(response, "filtered@example.com")


@skip_unless_lms
class LogistrationPageFiltersTest(UserAPITestCase):
    """
    Tests for the Open edX Filters associated with the legacy logistration page.

    This class guarantees that the following filters are triggered while the combined
    login/registration page is rendered:

    - LogistrationContextRequested
    - LogistrationResponseRendered
    - LogistrationMFERedirectRequested
    """

    def setUp(self):  # pylint: disable=arguments-differ
        super().setUp()
        self.url = reverse("signin_user")

    @override_settings(
        OPEN_EDX_FILTERS_CONFIG={
            "org.openedx.learning.logistration.context.requested.v1": {
                "pipeline": [
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestLogistrationContextPipelineStep",
                ],
                "fail_silently": False,
            },
        },
    )
    def test_logistration_context_filter_executed(self):
        """
        Test whether the logistration context filter is triggered before the page is rendered.

        Expected result:
            - LogistrationContextRequested is triggered and executes TestLogistrationContextPipelineStep.
            - The platform name overridden by the pipeline step is rendered into the page.
        """
        response = self.client.get(self.url, HTTP_ACCEPT="text/html")

        self.assertContains(response, "Filtered Platform Name")

    @override_settings(OPEN_EDX_FILTERS_CONFIG={})
    def test_logistration_context_without_filter_configuration(self):
        """
        Test usual logistration page rendering, without filter's intervention.

        Expected result:
            - LogistrationContextRequested does not have any effect on the context.
        """
        response = self.client.get(self.url, HTTP_ACCEPT="text/html")

        self.assertEqual(status.HTTP_200_OK, response.status_code)  # noqa: PT009
        self.assertNotContains(response, "Filtered Platform Name")

    @override_settings(
        OPEN_EDX_FILTERS_CONFIG={
            "org.openedx.learning.logistration.response.rendered.v1": {
                "pipeline": [
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestLogistrationResponsePipelineStep",
                ],
                "fail_silently": False,
            },
        },
    )
    def test_logistration_response_filter_executed(self):
        """
        Test whether the logistration response filter is triggered after the page is rendered.

        Expected result:
            - LogistrationResponseRendered is triggered and executes TestLogistrationResponsePipelineStep.
            - The cookie set by the pipeline step is present on the response.
        """
        response = self.client.get(self.url, HTTP_ACCEPT="text/html")

        self.assertEqual(status.HTTP_200_OK, response.status_code)  # noqa: PT009
        self.assertEqual(response.cookies["logistration-filter"].value, "applied")  # noqa: PT009

    @override_settings(OPEN_EDX_FILTERS_CONFIG={})
    def test_logistration_response_without_filter_configuration(self):
        """
        Test usual logistration page rendering, without filter's intervention.

        Expected result:
            - LogistrationResponseRendered does not have any effect on the response.
        """
        response = self.client.get(self.url, HTTP_ACCEPT="text/html")

        self.assertEqual(status.HTTP_200_OK, response.status_code)  # noqa: PT009
        self.assertNotIn("logistration-filter", response.cookies)  # noqa: PT009

    @patch(
        "openedx.core.djangoapps.user_authn.views.login_form.should_redirect_to_authn_microfrontend",
        Mock(return_value=True),
    )
    @override_settings(
        OPEN_EDX_FILTERS_CONFIG={
            "org.openedx.learning.logistration.mfe.redirect.requested.v1": {
                "pipeline": [
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestPreventMFERedirectPipelineStep",
                ],
                "fail_silently": False,
            },
        },
    )
    def test_mfe_redirect_filter_prevents_redirect(self):
        """
        Test preventing the redirect to the authn MFE through a pipeline step.

        Expected result:
            - LogistrationMFERedirectRequested is triggered and executes TestPreventMFERedirectPipelineStep.
            - The legacy logistration page is rendered instead of redirecting to the MFE.
        """
        response = self.client.get(self.url, HTTP_ACCEPT="text/html")

        self.assertEqual(status.HTTP_200_OK, response.status_code)  # noqa: PT009

    @patch(
        "openedx.core.djangoapps.user_authn.views.login_form.should_redirect_to_authn_microfrontend",
        Mock(return_value=True),
    )
    @override_settings(OPEN_EDX_FILTERS_CONFIG={})
    def test_mfe_redirect_without_filter_configuration(self):
        """
        Test usual redirect to the authn MFE, without filter's intervention.

        Expected result:
            - LogistrationMFERedirectRequested does not have any effect on the redirect.
            - The user is redirected to the authn MFE.
        """
        response = self.client.get(self.url, HTTP_ACCEPT="text/html")

        self.assertEqual(status.HTTP_302_FOUND, response.status_code)  # noqa: PT009
        self.assertEqual(response.url, settings.AUTHN_MICROFRONTEND_URL + "/login")  # noqa: PT009


@skip_unless_lms
class PostLoginRedirectFiltersTest(UserAPITestCase):
    """
    Tests for the Open edX Filters associated with the post-login redirect URL.

    This class guarantees that the following filters are triggered after a successful login:

    - PostLoginRedirectURLRequested
    """

    def setUp(self):  # pylint: disable=arguments-differ
        super().setUp()
        self.user = UserFactory.create(
            username="test",
            email="test@example.com",
            password="password",
        )
        self.user_profile = UserProfileFactory.create(user=self.user, name="Test Example")
        self.url = reverse("login_api")

    @patch(
        "openedx.core.djangoapps.user_authn.views.login.should_redirect_to_authn_microfrontend",
        Mock(return_value=True),
    )
    @override_settings(
        OPEN_EDX_FILTERS_CONFIG={
            "org.openedx.learning.auth.post_login.redirect_url.requested.v1": {
                "pipeline": [
                    "openedx.core.djangoapps.user_authn.views.tests.test_filters.TestPostLoginRedirectPipelineStep",
                ],
                "fail_silently": False,
            },
        },
    )
    def test_post_login_redirect_filter_executed(self):
        """
        Test whether the post-login redirect filter is triggered after a successful login.

        Expected result:
            - PostLoginRedirectURLRequested is triggered and executes TestPostLoginRedirectPipelineStep.
            - The redirect URL returned in the response comes from the pipeline step.
        """
        data = {
            "email": "test@example.com",
            "password": "password",
        }

        response = self.client.post(self.url, data)

        self.assertEqual(status.HTTP_200_OK, response.status_code)  # noqa: PT009
        self.assertTrue(response.json()["redirect_url"].endswith("/custom/post/login"))  # noqa: PT009

    @patch(
        "openedx.core.djangoapps.user_authn.views.login.should_redirect_to_authn_microfrontend",
        Mock(return_value=True),
    )
    @override_settings(OPEN_EDX_FILTERS_CONFIG={})
    def test_post_login_redirect_without_filter_configuration(self):
        """
        Test usual post-login redirect, without filter's intervention.

        Expected result:
            - PostLoginRedirectURLRequested does not have any effect on the redirect URL.
            - The user is redirected to the default next URL.
        """
        data = {
            "email": "test@example.com",
            "password": "password",
        }

        response = self.client.post(self.url, data)

        self.assertEqual(status.HTTP_200_OK, response.status_code)  # noqa: PT009
        self.assertTrue(response.json()["redirect_url"].endswith("/dashboard"))  # noqa: PT009
