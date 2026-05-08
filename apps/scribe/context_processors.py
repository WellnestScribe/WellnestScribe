"""Inject doctor UI preferences + feature flags into every template."""

from pathlib import Path

from django.conf import settings

from accounts.models import DoctorProfile


def _ui_asset_version() -> str:
    candidates = (
        settings.BASE_DIR / "static" / "css" / "wellnest.css",
        settings.BASE_DIR / "static" / "js" / "wellnest.js",
        settings.BASE_DIR / "templates" / "service-worker.js",
        settings.BASE_DIR / "wellnest" / "pwa.py",
    )
    mtimes = [
        int(path.stat().st_mtime)
        for path in candidates
        if isinstance(path, Path) and path.exists()
    ]
    return str(max(mtimes) if mtimes else 1)


def ui_preferences(request):
    profile = None
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        profile = DoctorProfile.objects.filter(user=user).first()

    if not user or not user.is_authenticated:
        triage_visible = False
        is_admin = False
    elif settings.SCRIBE_ENABLE_TRIAGE:
        triage_visible = True
        is_admin = bool(profile and profile.is_admin) or user.is_staff
    else:
        is_admin = bool(profile and profile.is_admin) or user.is_staff or user.is_superuser
        triage_visible = bool(profile and profile.can_access_triage()) or is_admin

    return {
        "doctor_profile": profile,
        "ui_font_scale": profile.font_scale if profile else 100,
        "ui_theme": profile.theme if profile else "light",
        "ui_asset_version": _ui_asset_version(),
        "triage_visible": triage_visible,
        "is_admin": is_admin,
    }
