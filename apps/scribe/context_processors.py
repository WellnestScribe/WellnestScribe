"""Inject doctor UI preferences (font scale, theme) into every template."""

from accounts.models import DoctorProfile


def ui_preferences(request):
    profile = None
    if getattr(request, "user", None) and request.user.is_authenticated:
        profile = DoctorProfile.objects.filter(user=request.user).first()
    return {
        "doctor_profile": profile,
        "ui_font_scale": profile.font_scale if profile else 100,
        "ui_theme": profile.theme if profile else "light",
    }
