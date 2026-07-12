"""Security signal receivers for the IDS.

Records failed login attempts as SecurityEvents so brute-force / credential
stuffing shows up on the intrusion-detection dashboard. Kept intentionally thin
and failure-proof — telemetry must never block authentication.
"""
from __future__ import annotations

from django.contrib.auth.signals import user_login_failed
from django.dispatch import receiver


def _client_ip(request) -> str | None:
    if request is None:
        return None
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR") or None


@receiver(user_login_failed)
def _on_login_failed(sender, credentials=None, request=None, **kwargs):
    try:
        from .models import SecurityEvent
        username = ""
        if credentials:
            username = credentials.get("username") or credentials.get("email") or ""
        SecurityEvent.record(
            SecurityEvent.LOGIN_FAILED,
            severity=SecurityEvent.SEV_WARNING,
            ip=_client_ip(request),
            username=username,
            path=getattr(request, "path", "") if request else "",
            user_agent=(request.META.get("HTTP_USER_AGENT", "") if request else ""),
            detail="Invalid credentials",
        )
    except Exception:  # noqa: BLE001 — never break auth on telemetry failure
        pass
