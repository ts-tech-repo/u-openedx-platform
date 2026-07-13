from django.http import JsonResponse


def ping(request):
    return JsonResponse(
        {
            "app": "common",
            "status": "ok"
        }
    )