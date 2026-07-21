from django.http import JsonResponse

from c_ptc.helpers import _get_user
from common.djangoapps.edxmako.shortcuts import render_to_response


def health(request):
    return JsonResponse(
        {
            "app": "c_ptc",
            "status": "ok"
        }
    )


def fetch_ptc(request, ptc_type):

    user = _get_user(request)
    if not user:
        return render_to_response(
            "c_ptc/show_message.html",
            {
                "message": "User not found or not authenticated.",
                "status": "error"
            }
        )
    


    return JsonResponse(
        {
            "app": "c_ptc",
            "status": "ok"
        }
    )

def submit_ptc(request, ptc_type):
    return JsonResponse(
        {
            "app": "c_ptc",
            "status": "ok"
        }
    )