import json

from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import never_cache


@never_cache
def manifest_view(request):
    payload = {
        "name": "WellNest Scribe",
        "short_name": "WellNest",
        "description": "Voice-to-SOAP clinical note capture for Caribbean healthcare teams.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "background_color": "#f5faff",
        "theme_color": "#0c7ec2",
        "icons": [
            {
                "src": static("images/pwa/icon-192x192.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": static("images/pwa/icon-512x512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
    }
    return HttpResponse(
        json.dumps(payload, indent=2),
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
