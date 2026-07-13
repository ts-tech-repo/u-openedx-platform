from django.http import JsonResponse


def health(request):
    return JsonResponse(
        {
            "app": "custom_cms",
            "status": "ok"
        }
    )