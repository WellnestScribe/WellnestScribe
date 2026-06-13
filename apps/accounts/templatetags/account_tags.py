from django import template

register = template.Library()

_AVATAR_COLORS = [
    "#1a6fd4", "#2e7d32", "#c62828", "#7b1fa2", "#e65100",
    "#1565c0", "#558b2f", "#d32f2f", "#6a1b9a", "#bf360c",
    "#0277bd", "#33691e", "#b71c1c", "#4a148c", "#e64a19",
]


@register.filter
def ua_initials(user):
    """Return 1-2 letter initials for a User object."""
    try:
        profile = user.doctor_profile
        name = profile.full_name or ""
    except Exception:
        name = ""
    if not name:
        name = (user.get_full_name() or user.username or "").strip()
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if name:
        return name[:2].upper()
    return "?"


@register.filter
def ua_avatar_color(pk):
    """Return a consistent hex color for a given user PK integer."""
    try:
        return _AVATAR_COLORS[int(pk) % len(_AVATAR_COLORS)]
    except (TypeError, ValueError):
        return _AVATAR_COLORS[0]
