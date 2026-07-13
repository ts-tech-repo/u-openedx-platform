import logging

from django.http import JsonResponse
from django.contrib.auth.models import User
from django.conf import settings

from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny

from openedx.core.djangoapps.oauth_dispatch.jwt import create_jwt_for_user

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