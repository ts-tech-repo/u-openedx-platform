import logging

from django.http import JsonResponse, HttpResponse
from django.contrib.auth.models import User
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.conf import settings
from django.utils.http import int_to_base36

from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication

from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny, IsAuthenticated

from openedx.core.djangoapps.oauth_dispatch.jwt import create_jwt_for_user
from openedx.core.djangoapps.user_authn.toggles import should_redirect_to_authn_microfrontend

log = logging.getLogger(__name__)

def ping(request):
    return JsonResponse(
        {
            "app": "common",
            "status": "ok"
        }
    )

@api_view(['POST'])
@authentication_classes(())
@permission_classes([AllowAny])
def extras_generate_jwt_token(request):

    username = request.headers.get("username")
    password = request.headers.get("password")

    try:
        user_obj = User.objects.get(username = username)
        if not user_obj.check_password(password):
            return JsonResponse({"error": "Invalid credentials"}, status=401)

        token = create_jwt_for_user(user_obj)
        return JsonResponse({"jwtToken" : token, "expiry" : settings.OAUTH_ID_TOKEN_EXPIRATION})

    except Exception as err:
        log.info("Something went wrong {0}".format(err))
        return JsonResponse({"error": "Invalid credentials/parameters"}, status=501)

def _get_password_reset_link(user, domain):
    uid = int_to_base36(user.id)
    token = PasswordResetTokenGenerator().make_token(user)
    mfe_url_addon = "/authn" if should_redirect_to_authn_microfrontend() else ""
    url = "https://{0}{1}/password_reset_confirm/{2}-{3}".format(domain, mfe_url_addon, uid, token)
    return url

@api_view(['POST'])
@authentication_classes([JwtAuthentication])
@permission_classes([IsAuthenticated])
def extras_reset_password_link(request):
    email = request.POST.get("email")
    domain = request.META["HTTP_HOST"]
    action = request.POST.get("action", None)

    response = {
        "error" : True,
        "message" : "Something went wrong! Try again.",
        "data": {}
    }

    if action and action == 'reset':
        username = request.POST.get("username", None)

        if not username:
            response["message"] = "username parameter is required"
            return JsonResponse(response)

        user_with_email = User.objects.filter(email__iexact=email.strip()).first()
        user_with_username = User.objects.filter(username__iexact=username.strip()).first()

        isValidated = False

        if not user_with_email and not user_with_username:
            response["message"] = f"In {domain}, User not found with requested username and email"
        elif user_with_email and not user_with_username:
            if user_with_email.username != username:
                response["message"] = f"In {domain}, User exists with email but requested username (i.e., {username}) didn't matched with its username"
            else:
                isValidated = True
        elif not user_with_email and user_with_username:
            if user_with_username.email != email:
                response["message"] = f"In {domain}, User exists with username but requested email (i.e., {email}) didn't matched with its email"
            else:
                isValidated = True
        elif user_with_email and user_with_username:
            if user_with_email.email != user_with_username.email and user_with_email.username != user_with_username.username:
                response["message"] = f"In {domain}, 2 users exists with requested email and username"
            elif user_with_email.email != user_with_username.email and user_with_email.username == user_with_username.username:
                response["message"] = f"In {domain}, User exists with requested username but not with requested email"
            elif user_with_email.email == user_with_username.email and user_with_email.username != user_with_username.username:
                response["message"] = f"In {domain}, User exists with requested email but not with requested username"
            else:
                isValidated = True

        if isValidated:
            response["error"] = False
            response["message"] = f"In {domain}, User exists with requested email and username"
            response["data"] = { "reset_link": _get_password_reset_link(user_with_email, domain) }

        return JsonResponse(response)
    else:
        try:
            user = User.objects.get(email__iexact=email.strip())
        except Exception as err:
            log.error("Reset Password Error: "+ str(err) + " Email:" + email)
            return HttpResponse("")
        uid = int_to_base36(user.id)
        token = PasswordResetTokenGenerator().make_token(user)
        mfe_url_addon = "/authn" if should_redirect_to_authn_microfrontend() else ""
        url = "https://{0}{1}/password_reset_confirm/{2}-{3}".format(domain, mfe_url_addon, uid, token)
        return HttpResponse(url)
