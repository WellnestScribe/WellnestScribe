from django.shortcuts import render
from django.views.decorators.cache import never_cache


@never_cache
def manifest_view(request):
    return render(
        request,
        "manifest.webmanifest",
        content_type="application/manifest+json",
    )


@never_cache
def service_worker_view(request):
    response = render(
        request,
        "service-worker.js",
        content_type="application/javascript",
    )
    response["Service-Worker-Allowed"] = "/"
    return response
