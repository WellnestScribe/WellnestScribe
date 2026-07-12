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
    else:
        is_admin = bool(profile and profile.is_admin) or user.is_staff or user.is_superuser
        # Triage Lab is an admin-only internal tool (QA / benchmarking) - it must
        # not appear for doctors/nurses. The env flag is a master enable;
        # visibility now additionally requires admin.
        triage_visible = is_admin and settings.SCRIBE_ENABLE_TRIAGE

    is_org_admin = False
    if not is_admin and user and user.is_authenticated:
        try:
            from emr.models import OrganisationMembership
            is_org_admin = OrganisationMembership.objects.filter(
                user=user, role__in=["admin", "system_admin"]
            ).exists()
        except Exception:
            pass

    idle_lock_ms = 0
    if user and user.is_authenticated:
        idle_lock_minutes = getattr(settings, "IDLE_LOCK_MINUTES", 15)
        idle_lock_ms = idle_lock_minutes * 60 * 1000 if idle_lock_minutes > 0 else 0

    return {
        "doctor_profile": profile,
        "ui_font_scale": profile.font_scale if profile else 100,
        "ui_theme": profile.theme if profile else "light",
        "ui_asset_version": _ui_asset_version(),
        "triage_visible": triage_visible,
        "is_admin": is_admin,
        "is_org_admin": is_org_admin,
        "idle_lock_ms": idle_lock_ms,
        "last_login_ip": profile.last_login_ip if profile else None,
        "last_login_at": profile.last_login_at if profile else None,
        "previous_login_ip": profile.previous_login_ip if profile else None,
    }
