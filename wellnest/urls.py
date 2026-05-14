from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect, render
from django.urls import include, path

from .pwa import manifest_view, service_worker_view


def root_view(request):
    """Authenticated users go straight to the scribe; everyone else sees the landing page."""
    if request.user.is_authenticated:
        return redirect("scribe:record")
    return render(request, "landing.html")


urlpatterns = [
    path("", root_view, name="root"),
    path("manifest.webmanifest", manifest_view, name="manifest"),
    path("service-worker.js", service_worker_view, name="service_worker"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("emr/", include("emr.urls")),
    path("scribe/", include("scribe.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
